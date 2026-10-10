"""Regras puras dos disparos (sem banco e sem request): orçamento de envio, contadores, máquina de estados,
parâmetros do template oficial, montagem da mensagem, agendamento e instrução de descadastro.

Usado pelas views, pelos formulários, pelo processador da fila (worker) e coberto por apps/messaging/tests.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from typing import Any
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo

from apps.core.constants import OPT_OUT_KEYWORDS, BroadcastStatus, MessageStatus
from apps.core.template_vars import VARIABLE_KEYS
from apps.whatsapp.types import MediaAttachment, OutgoingMessage, TemplateCall

# --------------------------------------------------------------------------------------------- constantes

CAMPAIGN_TZ = ZoneInfo("America/Sao_Paulo")

#: Tentativas automáticas (erros temporários) antes de marcar a mensagem como FAILED
MAX_AUTO_ATTEMPTS = 3
#: Limite total de tentativas, contando os reenvios manuais ("Reenviar falhas")
MAX_MANUAL_ATTEMPTS = 5
#: Mensagens presas em SENDING por mais que isso voltam para a fila
STUCK_SENDING_SECONDS = 5 * 60
#: Janela do limite de envio por minuto
RATE_WINDOW_SECONDS = 60
#: Antecedência máxima de um agendamento
MAX_SCHEDULE_DAYS = 180
#: Tamanho máximo do texto de um modelo
TEMPLATE_BODY_MAX = 4096
#: Velocidade máxima aceita para um disparo (a conexão ainda limita)
MAX_RATE_PER_MINUTE = 1000
#: Padrão sugerido de velocidade
DEFAULT_RATE_PER_MINUTE = 20

#: Status de disparo que impedem excluir o modelo usado
TEMPLATE_LOCKING_STATUSES = (BroadcastStatus.SCHEDULED, BroadcastStatus.RUNNING, BroadcastStatus.PAUSED)
#: Status em que as telas se atualizam sozinhas
ACTIVE_BROADCAST_STATUSES = (BroadcastStatus.SCHEDULED, BroadcastStatus.RUNNING)

OPT_OUT_INSTRUCTION = "Responda SAIR para não receber mais mensagens."

#: Nome de template aprovado da Meta/360dialog (minúsculas, números e _) ou ContentSid da Twilio (HX + 32 hex)
PROVIDER_TEMPLATE_NAME_RE = re.compile(r"^(?:[a-z0-9_]{1,120}|HX[0-9a-fA-F]{32})$")
#: Código de idioma do template (ex.: pt_BR, en_US, es)
PROVIDER_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(?:_[A-Z]{2})?$")


def is_active_status(status: str) -> bool:
    return status in ACTIVE_BROADCAST_STATUSES


# --------------------------------------------------------------------------------------------- orçamento de envio


def compute_send_budget(
    *,
    connection_rate: int,
    connection_sent_last_minute: int,
    broadcast_rate: int,
    broadcast_sent_last_minute: int,
    tick_remaining: int,
) -> int:
    """Quantas mensagens o disparo pode enviar agora (nunca negativo).

    - da conexão: limite por minuto − enviadas pela conexão (todos os disparos) nos últimos 60 s;
    - do disparo: min(limite do disparo, limite da conexão) − enviadas por ele nos últimos 60 s;
    - do ciclo: o que ainda cabe em `max_messages`.
    """
    conn = max(0, int(connection_rate) - int(connection_sent_last_minute))
    own = max(0, min(int(broadcast_rate), int(connection_rate)) - int(broadcast_sent_last_minute))
    return max(0, min(conn, own, int(tick_remaining)))


# --------------------------------------------------------------------------------------------- contadores


@dataclass(frozen=True)
class Counters:
    total: int = 0
    pending: int = 0
    sending: int = 0
    #: SENT + DELIVERED + READ
    sent: int = 0
    #: DELIVERED + READ
    delivered: int = 0
    read: int = 0
    failed: int = 0
    skipped: int = 0

    @property
    def queued(self) -> int:
        """PENDING + SENDING"""
        return self.pending + self.sending

    @property
    def processed(self) -> int:
        """Mensagens já resolvidas: enviadas + falhas + ignoradas"""
        return self.sent + self.failed + self.skipped


def counters_from_groups(rows: Mapping[str, int] | Iterable[tuple[str, int]]) -> Counters:
    """Contagem por status ({status: n} ou pares) → contadores do disparo."""
    pairs = rows.items() if isinstance(rows, Mapping) else rows
    by: dict[str, int] = {}
    total = 0
    for status, count in pairs:
        by[status] = by.get(status, 0) + int(count)
        total += int(count)

    def n(status: str) -> int:
        return by.get(status, 0)

    return Counters(
        total=total,
        pending=n(MessageStatus.PENDING),
        sending=n(MessageStatus.SENDING),
        sent=n(MessageStatus.SENT) + n(MessageStatus.DELIVERED) + n(MessageStatus.READ),
        delivered=n(MessageStatus.DELIVERED) + n(MessageStatus.READ),
        read=n(MessageStatus.READ),
        failed=n(MessageStatus.FAILED),
        skipped=n(MessageStatus.SKIPPED),
    )


def should_complete(status: str, pending: int, sending: int) -> bool:
    """Disparo em andamento sem nada na fila → concluído."""
    return status == BroadcastStatus.RUNNING and pending + sending == 0


def percent(part: float, whole: float) -> float:
    """Percentual (0–100) com proteção contra divisão por zero."""
    if not whole or whole <= 0:
        return 0.0
    return min(100.0, max(0.0, part / whole * 100))


def broadcast_rates(sent: int, delivered: int, read: int) -> tuple[float, float]:
    """(taxa de entrega, taxa de leitura): entregues sobre enviadas; lidas sobre entregues."""
    return percent(delivered, sent), percent(read, delivered)


# --------------------------------------------------------------------------------------------- máquina de estados

CONTROLS = ("pause", "resume", "cancel", "retry")

_TRANSITIONS: dict[str, tuple[tuple[str, ...], str]] = {
    "pause": ((BroadcastStatus.RUNNING,), BroadcastStatus.PAUSED),
    "resume": ((BroadcastStatus.PAUSED,), BroadcastStatus.RUNNING),
    "cancel": ((BroadcastStatus.SCHEDULED, BroadcastStatus.RUNNING, BroadcastStatus.PAUSED), BroadcastStatus.CANCELLED),
    "retry": ((BroadcastStatus.RUNNING, BroadcastStatus.COMPLETED), BroadcastStatus.RUNNING),
}

CONTROL_VERBS = {
    "pause": "pausar",
    "resume": "retomar",
    "cancel": "cancelar",
    "retry": "reenviar as falhas de",
}


def allowed_from(control: str) -> tuple[str, ...]:
    """Status de origem aceitos por uma ação (usado no filtro das atualizações condicionais)."""
    return _TRANSITIONS[control][0]


def next_broadcast_status(status: str, control: str) -> str | None:
    """Próximo status ao aplicar a ação, ou None se a ação não vale no status atual."""
    transition = _TRANSITIONS.get(control)
    if transition is None or status not in transition[0]:
        return None
    return transition[1]


def can_delete_broadcast(status: str) -> bool:
    """Disparo em andamento não pode ser excluído (pause ou cancele antes)."""
    return status != BroadcastStatus.RUNNING


def available_actions(status: str, *, retryable_failures: int, can_edit: bool, can_delete: bool) -> dict[str, bool]:
    """Ações disponíveis na tela de detalhe conforme status e permissões."""

    def ok(control: str) -> bool:
        return can_edit and next_broadcast_status(status, control) is not None

    return {
        "pause": ok("pause"),
        "resume": ok("resume"),
        "cancel": ok("cancel"),
        "retry": ok("retry") and retryable_failures > 0,
        "delete": can_delete and can_delete_broadcast(status),
    }


# --------------------------------------------------------------------------------------------- template oficial


def parse_provider_variables(value: Any) -> list[str]:
    """Lê MessageTemplate.provider_variables (JSON) com segurança: só chaves conhecidas, na ordem."""
    if not isinstance(value, (list, tuple)):
        return []
    return [v for v in value if isinstance(v, str) and v in VARIABLE_KEYS][:20]


def map_template_parameters(keys: Any, context: Mapping[str, Any]) -> list[str]:
    """Valores de {{1}}, {{2}}... do template aprovado, na ordem configurada.

    A API da Meta rejeita parâmetros vazios, com quebras de linha/tabulação ou com muitos espaços seguidos.
    """
    out = []
    for key in parse_provider_variables(keys):
        raw = str(context.get(key) if context.get(key) is not None else "")
        raw = re.sub(r"[\r\n\t]+", " ", raw)
        raw = re.sub(r" {2,}", " ", raw).strip()
        out.append(raw or "-")
    return out


# --------------------------------------------------------------------------------------------- mensagem de saída


def media_for_template(template: Any) -> MediaAttachment | None:
    """Mídia do modelo (somente URLs https; o provedor baixa o arquivo)."""
    kind = getattr(template, "type", "")
    url = (getattr(template, "media_url", "") or "").strip()
    if kind not in ("IMAGE", "DOCUMENT", "VIDEO") or not re.match(r"^https://", url, re.IGNORECASE):
        return None
    filename = ""
    if kind == "DOCUMENT":
        try:
            filename = unquote(urlparse(url).path.rsplit("/", 1)[-1])[:120]
        except ValueError:
            filename = ""
    return MediaAttachment(type=kind, url=url, filename=filename)


def build_outgoing_message(
    *,
    to: str,
    rendered_body: str,
    template: Any,
    requires_approved_template: bool,
    context: Mapping[str, Any],
) -> OutgoingMessage:
    """Monta a mensagem para o provedor a partir do texto já renderizado e do modelo."""
    message = OutgoingMessage(to=to, text=rendered_body)
    if template is None:
        return message
    message.media = media_for_template(template)
    name = (getattr(template, "provider_template_name", "") or "").strip()
    if requires_approved_template and name:
        message.template = TemplateCall(
            name=name,
            language=(getattr(template, "provider_template_language", "") or "pt_BR"),
            parameters=map_template_parameters(getattr(template, "provider_variables", None), context),
        )
    return message


@dataclass(frozen=True)
class SendBlocker:
    code: str
    message: str


def send_blocker(
    *,
    connection: Any,
    campaign_id: Any,
    provider_known: bool,
    requires_approved_template: bool,
    template: Any,
) -> SendBlocker | None:
    """Motivo para pausar/recusar em vez de enviar (conexão/provedor/modelo inadequados), ou None se está tudo certo."""
    if connection is None:
        return SendBlocker("connection_missing", "A conexão de WhatsApp do disparo foi excluída.")
    if connection.campaign_id != campaign_id:
        return SendBlocker("connection_campaign", "Conexão de WhatsApp inválida para esta campanha.")
    if connection.status != "CONNECTED":
        return SendBlocker("connection_status", "A conexão de WhatsApp não está conectada.")
    if not provider_known:
        return SendBlocker("provider_unknown", "Provedor de WhatsApp desconhecido.")
    if requires_approved_template and not (getattr(template, "provider_template_name", "") or "").strip():
        return SendBlocker(
            "template_required",
            "A API oficial exige template aprovado e o modelo não tem o nome do template aprovado.",
        )
    return None


def recipient_skip_reason(voter: Any, message: Any) -> str | None:
    """O eleitor ainda pode receber a mensagem? (o consentimento pode ter sido retirado depois do agendamento)."""
    if voter is None:
        return "Eleitor excluído"
    if voter.campaign_id != message.campaign_id:
        return "Eleitor de outra campanha"
    if voter.opt_out_at is not None:
        return "Eleitor pediu descadastro"
    if not voter.whatsapp_opt_in or voter.consent_at is None:
        return "Eleitor sem consentimento para WhatsApp"
    if voter.phone != message.phone:
        return "Telefone do eleitor foi alterado"
    return None


def truncate_error(error: object, limit: int = 300) -> str:
    """Texto de erro seguro para gravar (limitado ao tamanho do campo)."""
    if isinstance(error, BaseException):
        text = f"{type(error).__name__}: {error}" if str(error) else type(error).__name__
    elif isinstance(error, str):
        text = error
    else:
        text = ""
    return (text.strip() or "Erro desconhecido")[:limit]


def chunked(items: Sequence | Iterable, size: int) -> Iterator[list]:
    """Divide uma sequência em blocos de até `size` itens."""
    batch: list = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


# --------------------------------------------------------------------------------------------- agendamento

_LOCAL_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$")


def zoned_local_to_utc(local: str | None) -> datetime | None:
    """"2026-10-20T14:30" (horário de Brasília) → datetime aware em UTC. None se inválido (ex.: 31/02)."""
    match = _LOCAL_RE.match((local or "").strip())
    if not match:
        return None
    year, month, day, hour, minute = (int(match.group(i)) for i in range(1, 6))
    second = int(match.group(6) or 0)
    try:
        value = datetime(year, month, day, hour, minute, second, tzinfo=CAMPAIGN_TZ)
    except ValueError:
        return None
    return value.astimezone(dt_timezone.utc)


def to_local_input(value: datetime) -> str:
    """datetime → "YYYY-MM-DDTHH:MM" no fuso da campanha (valor para <input type="datetime-local">)."""
    return value.astimezone(CAMPAIGN_TZ).strftime("%Y-%m-%dT%H:%M")


@dataclass(frozen=True)
class ScheduleValidation:
    ok: bool
    date: datetime | None = None
    error: str = ""


def validate_schedule(local: str | None, now: datetime) -> ScheduleValidation:
    """Valida o horário de agendamento: precisa ser no futuro e dentro do limite de antecedência."""
    if not (local or "").strip():
        return ScheduleValidation(False, error="Informe a data e a hora do envio.")
    value = zoned_local_to_utc(local)
    if value is None:
        return ScheduleValidation(False, error="Data ou hora inválida.")
    if value <= now:
        return ScheduleValidation(False, error="Escolha um horário no futuro.")
    if value > now + timedelta(days=MAX_SCHEDULE_DAYS):
        return ScheduleValidation(
            False, error=f"O agendamento pode ser feito para no máximo {MAX_SCHEDULE_DAYS} dias à frente."
        )
    return ScheduleValidation(True, date=value)


def estimate_duration_minutes(count: int, rate_per_minute: int) -> int:
    """Duração estimada (minutos) para enviar `count` mensagens a `rate_per_minute`."""
    if count <= 0:
        return 0
    return -(-count // max(1, rate_per_minute))  # teto


def format_duration(minutes: float) -> str:
    """0 → "—"; 1 → "cerca de 1 min"; 135 → "cerca de 2 h 15 min"; 1500 → "cerca de 1 dia e 1 h"."""
    if not minutes or minutes <= 0:
        return "—"
    total = math.ceil(minutes)
    if total < 60:
        return f"cerca de {total} min"
    days, rest = divmod(total, 1440)
    hours, mins = divmod(rest, 60)
    if days > 0:
        return f"cerca de {days} {'dia' if days == 1 else 'dias'}" + (f" e {hours} h" if hours else "")
    return f"cerca de {hours} h" + (f" {mins:02d} min" if mins else "")


# --------------------------------------------------------------------------------------------- descadastro


def has_opt_out_instruction(body: str) -> bool:
    """O texto explica como deixar de receber mensagens (ex.: "responda SAIR")?"""
    normalized = "".join(
        c for c in unicodedata.normalize("NFD", body or "") if unicodedata.category(c) != "Mn"
    ).upper()
    return any(re.search(rf"(^|[^A-Z0-9]){keyword}([^A-Z0-9]|$)", normalized) for keyword in OPT_OUT_KEYWORDS)


def append_opt_out_instruction(body: str) -> str:
    trimmed = (body or "").rstrip()
    return f"{trimmed}\n\n{OPT_OUT_INSTRUCTION}" if trimmed else OPT_OUT_INSTRUCTION
