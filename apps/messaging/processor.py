"""Processador da fila de disparos. SEM imports de request/messages/decorators: roda no worker
(`manage.py run_worker`), em /api/cron/tick/ e no botão "Processar fila agora".

Cada ciclo (`run_queue_tick`):
  1. devolve à fila as mensagens presas em SENDING e encerra pendências de disparos cancelados;
  2. materializa os disparos agendados que venceram (uma mensagem por apoiador apto);
  3. envia as mensagens dos disparos em andamento respeitando o limite por minuto da conexão e do disparo;
  4. atualiza os contadores e conclui os disparos sem pendências;
  5. (ciclo global) geocodifica alguns apoiadores pendentes.

Consentimento (MESSAGEABLE_Q) é exigido na materialização E conferido de novo no momento do envio.
Nada aqui grava dados pessoais em log ou auditoria: apenas ids e contagens.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.auditlog.service import audit
from apps.core.access import voters_queryset
from apps.core.constants import CAMPAIGN_ROLES, BroadcastStatus, CampaignStatus, MessageStatus
from apps.core.template_vars import build_template_context, render_template
from apps.core.voter_filters import sanitize_voter_filters
from apps.whatsapp import registry
from apps.whatsapp.types import SendResult

from .counters import recompute_broadcast_counters
from .logic import (
    MAX_AUTO_ATTEMPTS,
    RATE_WINDOW_SECONDS,
    STUCK_SENDING_SECONDS,
    build_outgoing_message,
    chunked,
    compute_send_budget,
    recipient_skip_reason,
    send_blocker,
    truncate_error,
)
from .models import Broadcast, BroadcastMessage

logger = logging.getLogger(__name__)

DEFAULT_MAX_MESSAGES = 200
VOTER_PAGE = 2000
INSERT_CHUNK = 500
DUE_BATCH = 20
#: A cada N mensagens confere se o disparo continua RUNNING (pausa/cancelamento durante o envio)
STATUS_RECHECK_EVERY = 10
#: Erros temporários seguidos que interrompem o disparo no ciclo (limite do provedor, instabilidade)
MAX_CONSECUTIVE_TEMP_ERRORS = 3
#: Janela (minutos) em que um disparo mexido recentemente ainda conta para o limite por minuto da conexão
RECENT_ACTIVITY_MINUTES = 5


@dataclass
class MaterializeResult:
    #: RUNNING | COMPLETED | FAILED | SKIPPED (não estava mais agendado: outro processo já assumiu)
    status: str
    recipients: int = 0
    reason: str = ""

    @property
    def started(self) -> bool:
        return self.status in (BroadcastStatus.RUNNING, BroadcastStatus.COMPLETED)


# --------------------------------------------------------------------------------------------- materialização


def _valid_filters(raw) -> dict | None:
    """Filtros salvos válidos (sem `messageable`) ou None. Filtros inválidos NUNCA viram "todos os apoiadores"."""
    if not isinstance(raw, dict):
        return None
    stored = {k: v for k, v in raw.items() if k != "messageable" and v not in (None, "", [])}
    clean = sanitize_voter_filters(stored)
    return clean if clean == stored else None


def _voter_pages(queryset):
    """Percorre o queryset por paginação de chave (id), sem carregar todos os apoiadores na memória."""
    queryset = queryset.order_by("id")
    last_id = None
    while True:
        page = list((queryset.filter(id__gt=last_id) if last_id else queryset)[:VOTER_PAGE])
        if not page:
            return
        yield page
        if len(page) < VOTER_PAGE:
            return
        last_id = page[-1].id


def materialize_broadcast(broadcast, now: datetime | None = None) -> MaterializeResult:
    """Gera as mensagens (uma por telefone) de um disparo SCHEDULED e o coloca em RUNNING (ou COMPLETED, se
    ninguém estiver apto). O público é sempre limitado ao escopo de quem criou o disparo e somente a apoiadores
    que consentiram (`messageable` é forçado aqui, nunca salvo nos filtros)."""
    now = now or timezone.now()
    pk = getattr(broadcast, "pk", broadcast)
    b = Broadcast.objects.select_related("template", "campaign", "created_by").filter(pk=pk).first()
    if b is None or b.status != BroadcastStatus.SCHEDULED:
        return MaterializeResult("SKIPPED")

    def fail(reason: str) -> MaterializeResult:
        changed = Broadcast.objects.filter(pk=b.pk, status=BroadcastStatus.SCHEDULED).update(
            status=BroadcastStatus.FAILED, finished_at=now, updated_at=now
        )
        if changed != 1:
            return MaterializeResult("SKIPPED")
        audit(
            "broadcast.fail",
            campaign_id=b.campaign_id,
            entity="Broadcast",
            entity_id=b.pk,
            details={"automatic": True, "reason": reason},
        )
        return MaterializeResult("FAILED", reason=reason)

    creator = b.created_by
    if (
        creator is None
        or not creator.is_active
        or creator.campaign_id != b.campaign_id
        or creator.role not in CAMPAIGN_ROLES
    ):
        return fail("O usuário que criou o disparo foi desativado ou removido.")
    if b.campaign.status != CampaignStatus.ACTIVE:
        return fail("A campanha está suspensa.")
    template = b.template
    if template is None or template.campaign_id != b.campaign_id:
        return fail("O modelo de mensagem foi excluído.")
    filters = _valid_filters(b.filters)
    if filters is None:
        return fail("Os filtros do público são inválidos.")

    audience = voters_queryset(creator, {**filters, "messageable": True}).select_related("registered_by")

    with transaction.atomic():
        # Assume o disparo ANTES de gravar as mensagens, na mesma transação: ninguém vê RUNNING sem as mensagens e
        # dois processos nunca materializam o mesmo disparo (o segundo UPDATE espera e encontra status != SCHEDULED).
        claimed = Broadcast.objects.filter(pk=b.pk, status=BroadcastStatus.SCHEDULED).update(
            status=BroadcastStatus.RUNNING, started_at=now, finished_at=None, updated_at=now
        )
        if claimed != 1:
            return MaterializeResult("SKIPPED")
        total = 0
        seen_phones: set[str] = set()
        for voters in _voter_pages(audience):
            rows = []
            for voter in voters:
                if voter.phone in seen_phones:
                    continue
                seen_phones.add(voter.phone)
                context = build_template_context(voter, b.campaign, voter.registered_by)
                rows.append(
                    BroadcastMessage(
                        broadcast=b,
                        campaign_id=b.campaign_id,
                        voter=voter,
                        phone=voter.phone,
                        rendered_body=render_template(template.body, context),
                        status=MessageStatus.PENDING,
                    )
                )
            for part in chunked(rows, INSERT_CHUNK):
                BroadcastMessage.objects.bulk_create(part)
                total += len(part)
        if total > 0:
            Broadcast.objects.filter(pk=b.pk).update(total_recipients=total, updated_at=now)
        else:
            Broadcast.objects.filter(pk=b.pk).update(
                status=BroadcastStatus.COMPLETED, finished_at=now, total_recipients=0, updated_at=now
            )
    return MaterializeResult(BroadcastStatus.RUNNING if total > 0 else BroadcastStatus.COMPLETED, recipients=total)


# --------------------------------------------------------------------------------------------- envio


def _auto_pause(b: Broadcast, reason: str) -> None:
    """Pausa automaticamente um disparo que não pode enviar, registrando o motivo."""
    changed = Broadcast.objects.filter(pk=b.pk, status=BroadcastStatus.RUNNING).update(
        status=BroadcastStatus.PAUSED, updated_at=timezone.now()
    )
    if changed == 1:
        audit(
            "broadcast.pause",
            campaign_id=b.campaign_id,
            entity="Broadcast",
            entity_id=b.pk,
            details={"automatic": True, "reason": reason},
        )


def _update_message(message_id, from_status: str, **fields) -> int:
    """Atualização condicional (só se a mensagem ainda estiver em `from_status`)."""
    return BroadcastMessage.objects.filter(pk=message_id, status=from_status).update(
        updated_at=timezone.now(), **fields
    )


@dataclass
class _TickState:
    now: datetime
    remaining: int
    report: dict
    providers: dict = field(default_factory=dict)
    #: mensagens enviadas por conexão na janela de 1 minuto (banco + este ciclo)
    connection_usage: dict = field(default_factory=dict)


def _load_provider(connection, state: _TickState):
    if connection.pk not in state.providers:
        try:
            state.providers[connection.pk] = registry.provider_for_connection(connection)
        except Exception as exc:  # noqa: BLE001 — credenciais ilegíveis, provedor indisponível...
            logger.error("Falha ao carregar o provedor de WhatsApp (%s)", type(exc).__name__)
            state.providers[connection.pk] = None
    return state.providers[connection.pk]


def _send_for_broadcast(b: Broadcast, state: _TickState) -> None:
    connection = b.connection
    definition = registry.get_provider_definition(connection.provider) if connection is not None else None
    blocker = send_blocker(
        connection=connection,
        campaign_id=b.campaign_id,
        provider_known=definition is not None,
        requires_approved_template=bool(definition and definition.requires_approved_template),
        template=b.template,
    )
    if blocker is not None or connection is None or definition is None:
        _auto_pause(b, blocker.message if blocker else "Conexão de WhatsApp indisponível.")
        return
    provider = _load_provider(connection, state)
    if provider is None:
        _auto_pause(b, "Não foi possível carregar as credenciais da conexão de WhatsApp.")
        return

    window_start = state.now - timedelta(seconds=RATE_WINDOW_SECONDS)
    if connection.pk not in state.connection_usage:
        # Só disparos mexidos há pouco podem ter enviado algo no último minuto (cada ciclo atualiza `updated_at` do
        # disparo que enviou): evita varrer o histórico inteiro de mensagens de disparos antigos a cada ciclo.
        recent_broadcasts = Broadcast.objects.filter(
            connection_id=connection.pk, updated_at__gte=state.now - timedelta(minutes=RECENT_ACTIVITY_MINUTES)
        ).values("pk")
        state.connection_usage[connection.pk] = BroadcastMessage.objects.filter(
            broadcast_id__in=recent_broadcasts, sent_at__gte=window_start
        ).count()
    own_sent = BroadcastMessage.objects.filter(broadcast_id=b.pk, sent_at__gte=window_start).count()
    budget = compute_send_budget(
        connection_rate=connection.rate_per_minute,
        connection_sent_last_minute=state.connection_usage[connection.pk],
        broadcast_rate=b.rate_per_minute,
        broadcast_sent_last_minute=own_sent,
        tick_remaining=state.remaining,
    )
    if budget <= 0:
        return

    pending = list(
        BroadcastMessage.objects.filter(broadcast_id=b.pk, status=MessageStatus.PENDING)
        .select_related("voter__registered_by")
        .order_by("created_at", "id")[:budget]
    )
    processed = 0
    temp_errors = 0
    for message in pending:
        if state.remaining <= 0:
            break
        # Respeita pausa/cancelamento feitos enquanto o ciclo envia
        if processed > 0 and processed % STATUS_RECHECK_EVERY == 0:
            current = Broadcast.objects.filter(pk=b.pk).values_list("status", flat=True).first()
            if current != BroadcastStatus.RUNNING:
                break
        processed += 1

        # Reserva atômica: só um processo envia cada mensagem
        claimed = BroadcastMessage.objects.filter(pk=message.pk, status=MessageStatus.PENDING).update(
            status=MessageStatus.SENDING, attempts=F("attempts") + 1, updated_at=timezone.now()
        )
        if claimed != 1:
            continue
        state.remaining -= 1
        attempts = message.attempts + 1

        voter = message.voter
        reason = recipient_skip_reason(voter, message)
        if reason is not None:
            _update_message(message.pk, MessageStatus.SENDING, status=MessageStatus.SKIPPED, error=reason)
            state.report["skipped"] += 1
            continue

        context = build_template_context(voter, b.campaign, voter.registered_by)
        outgoing = build_outgoing_message(
            to=message.phone,
            rendered_body=message.rendered_body,
            template=b.template,
            requires_approved_template=bool(definition.requires_approved_template),
            context=context,
        )
        try:
            result = provider.send(outgoing)
        except Exception as exc:  # noqa: BLE001 — qualquer falha do provedor vira erro temporário
            result = SendResult(ok=False, error=truncate_error(type(exc).__name__), retryable=True)

        if result.ok:
            temp_errors = 0
            sent_at = timezone.now()
            updated = _update_message(
                message.pk,
                MessageStatus.SENDING,
                status=MessageStatus.SENT,
                sent_at=sent_at,
                provider_message_id=(result.provider_message_id or "")[:200],
                error="",
            )
            if updated == 0:
                # O status já avançou (ex.: webhook de entrega chegou antes): só completa os dados do envio
                BroadcastMessage.objects.filter(pk=message.pk, sent_at__isnull=True).update(
                    sent_at=sent_at, provider_message_id=(result.provider_message_id or "")[:200]
                )
            state.connection_usage[connection.pk] = state.connection_usage.get(connection.pk, 0) + 1
            state.report["sent"] += 1
            continue

        retry = bool(result.retryable) and attempts < MAX_AUTO_ATTEMPTS
        _update_message(
            message.pk,
            MessageStatus.SENDING,
            status=MessageStatus.PENDING if retry else MessageStatus.FAILED,
            error=truncate_error(result.error or "Falha no envio"),
        )
        if not retry:
            state.report["failed"] += 1
        if result.retryable:
            temp_errors += 1
            if temp_errors >= MAX_CONSECUTIVE_TEMP_ERRORS:
                break
        else:
            temp_errors = 0


# --------------------------------------------------------------------------------------------- ciclo


def _recover_stuck(now: datetime, scope: dict, touched: set, report: dict) -> None:
    """Mensagens presas em SENDING (processo interrompido) voltam à fila; as que já esgotaram as tentativas falham."""
    stuck = BroadcastMessage.objects.filter(
        status=MessageStatus.SENDING,
        # parte dos disparos (poucos) para usar o índice (disparo, status) em vez de varrer todas as mensagens
        broadcast__status__in=(
            BroadcastStatus.RUNNING,
            BroadcastStatus.PAUSED,
            BroadcastStatus.CANCELLED,
            BroadcastStatus.FAILED,
        ),
        updated_at__lt=now - timedelta(seconds=STUCK_SENDING_SECONDS),
        **scope,
    )
    broadcast_ids = list(stuck.order_by().values_list("broadcast_id", flat=True).distinct())
    if not broadcast_ids:
        return
    failed = stuck.filter(attempts__gte=MAX_AUTO_ATTEMPTS).update(
        status=MessageStatus.FAILED, error="Sem confirmação do provedor após várias tentativas.", updated_at=now
    )
    stuck.update(status=MessageStatus.PENDING, updated_at=now)
    report["failed"] += failed
    touched.update(broadcast_ids)


def _skip_orphans(now: datetime, scope: dict, touched: set, report: dict) -> None:
    """Pendências de disparos cancelados/falhos nunca serão enviadas."""
    orphans = BroadcastMessage.objects.filter(
        status=MessageStatus.PENDING,
        broadcast__status__in=(BroadcastStatus.CANCELLED, BroadcastStatus.FAILED),
        **scope,
    )
    broadcast_ids = list(orphans.order_by().values_list("broadcast_id", flat=True).distinct())
    if not broadcast_ids:
        return
    report["skipped"] += orphans.update(status=MessageStatus.SKIPPED, error="Cancelado", updated_at=now)
    touched.update(broadcast_ids)


def run_queue_tick(campaign_id=None, max_messages: int = DEFAULT_MAX_MESSAGES, now: datetime | None = None) -> dict:
    """Um ciclo da fila. Seguro para rodar em paralelo (worker + cron): as reservas de mensagens são atômicas.

    `campaign_id` restringe o ciclo a uma campanha (botão "Processar fila agora"); sem ele é o ciclo global
    (que também geocodifica apoiadores pendentes). Retorna {materialized, sent, failed, skipped, completed, geocoded}.
    """
    now = now or timezone.now()
    max_messages = max(0, int(max_messages))
    report = {"materialized": 0, "sent": 0, "failed": 0, "skipped": 0, "completed": 0, "geocoded": 0}
    scope = {"campaign_id": campaign_id} if campaign_id else {}
    touched: set = set()

    # 1) Recuperação
    _recover_stuck(now, scope, touched, report)
    _skip_orphans(now, scope, touched, report)

    # 2) Agendados que venceram
    due = list(
        Broadcast.objects.filter(
            status=BroadcastStatus.SCHEDULED,
            scheduled_at__lte=now,
            campaign__status=CampaignStatus.ACTIVE,
            **scope,
        )
        .order_by("scheduled_at")
        .values_list("pk", "campaign_id")[:DUE_BATCH]
    )
    for broadcast_id, due_campaign_id in due:
        try:
            result = materialize_broadcast(broadcast_id, now)
        except Exception as exc:  # noqa: BLE001
            logger.error("Falha ao preparar disparo agendado %s (%s)", broadcast_id, type(exc).__name__)
            continue
        if result.started:
            report["materialized"] += 1
            if result.status == BroadcastStatus.COMPLETED:
                report["completed"] += 1
            audit(
                "broadcast.start",
                campaign_id=due_campaign_id,
                entity="Broadcast",
                entity_id=broadcast_id,
                details={"automatic": True, "recipients": result.recipients},
            )

    # 3) Envio
    if max_messages > 0:
        running = (
            Broadcast.objects.filter(status=BroadcastStatus.RUNNING, campaign__status=CampaignStatus.ACTIVE, **scope)
            .select_related("template", "connection", "campaign")
            .order_by("started_at", "created_at")
        )
        state = _TickState(now=now, remaining=max_messages, report=report)
        for b in running:
            if state.remaining <= 0:
                break
            touched.add(b.pk)
            try:
                _send_for_broadcast(b, state)
            except Exception as exc:  # noqa: BLE001
                logger.error("Falha ao enviar o disparo %s (%s)", b.pk, type(exc).__name__)

    # 4) Contadores / conclusão
    for broadcast_id in touched:
        try:
            if recompute_broadcast_counters(broadcast_id):
                report["completed"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("Falha ao atualizar contadores do disparo %s (%s)", broadcast_id, type(exc).__name__)

    # 5) Geocodificação pendente (somente no ciclo global do worker/cron)
    if not campaign_id:
        try:
            from apps.geo import geocode

            report["geocoded"] = int(geocode.process_pending_geocoding(5) or 0)
        except Exception as exc:  # noqa: BLE001
            logger.error("Falha na geocodificação pendente (%s)", type(exc).__name__)

    return report


def tick_had_activity(report: dict) -> bool:
    """O ciclo fez alguma coisa? (para logs resumidos)"""
    return any(report.get(key, 0) for key in ("materialized", "sent", "failed", "skipped", "completed", "geocoded"))
