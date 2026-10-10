"""Regras puras do webhook: progressão de status das mensagens, descadastro ("SAIR") e normalização de telefones
recebidos. Sem banco e sem rede (testável)."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from django.utils import timezone

from apps.core.constants import OPT_OUT_KEYWORDS, MessageStatus
from apps.core.phone import normalize_br_phone

# Ordem de progressão do ciclo normal de uma mensagem
_PROGRESS = {"PENDING": 0, "SENDING": 1, "SENT": 2, "DELIVERED": 3, "READ": 4}
ERROR_MAX_LENGTH = 300


def status_rank(status: str) -> int:
    """Ordem de aplicação dos eventos de um mesmo lote (FAILED por último)."""
    return 5 if status == "FAILED" else _PROGRESS.get(status, -1)


def next_message_status(current: str, incoming: str) -> str | None:
    """Próximo status de uma mensagem diante de um evento do provedor, ou None se nada muda.

    - O status só avança: SENT < DELIVERED < READ (eventos atrasados/duplicados são ignorados).
    - FAILED só vale se a mensagem ainda não foi entregue/lida.
    - Entrega/leitura confirmadas prevalecem sobre uma falha anterior.
    - SKIPPED (não enviada) nunca muda.
    """
    if current == MessageStatus.SKIPPED:
        return None
    if incoming == "FAILED":
        return None if current in (MessageStatus.DELIVERED, MessageStatus.READ, MessageStatus.FAILED) else "FAILED"
    if incoming not in _PROGRESS:
        return None
    if current == MessageStatus.FAILED:
        return None if incoming == "SENT" else incoming
    return incoming if _PROGRESS[incoming] > _PROGRESS.get(current, -1) else None


def build_status_update(
    row: Mapping[str, Any],
    status: str,
    *,
    error: str = "",
    timestamp: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Campos a atualizar na mensagem para um evento de status (None = ignorar).

    `row` tem as chaves status, sent_at, delivered_at, read_at.
    """
    nxt = next_message_status(row["status"], status)
    if nxt is None:
        return None
    at = timestamp or now or timezone.now()
    data: dict[str, Any] = {"status": nxt}
    if nxt == "FAILED":
        data["error"] = (error or "Falha na entrega informada pelo provedor")[:ERROR_MAX_LENGTH]
        return data
    if not row.get("sent_at"):
        data["sent_at"] = at
    if nxt in ("DELIVERED", "READ") and not row.get("delivered_at"):
        data["delivered_at"] = at
    if nxt == "READ" and not row.get("read_at"):
        data["read_at"] = at
    if row["status"] == MessageStatus.FAILED:
        data["error"] = ""
    return data


# Botões de descadastro dos templates de marketing da Meta
_EXTRA_OPT_OUT_PHRASES = ("PARAR PROMOCOES", "STOP PROMOTIONS")
OPT_OUT_PHRASES = frozenset((*OPT_OUT_KEYWORDS, *_EXTRA_OPT_OUT_PHRASES))


def normalize_opt_out_text(body: str | None) -> str:
    """Texto recebido sem acentos, em caixa alta, sem pontuação/emojis e com espaços únicos."""
    nfd = unicodedata.normalize("NFD", body or "")
    stripped = "".join(c for c in nfd if unicodedata.category(c) != "Mn").upper()
    cleaned = re.sub(r"[^A-Z0-9\s]+", "", stripped)
    return re.sub(r"\s+", " ", cleaned).strip()


def is_opt_out_message(body: str | None) -> bool:
    """A mensagem é um pedido de descadastro? (texto igual a uma das palavras-chave)"""
    normalized = normalize_opt_out_text(body)
    return normalized != "" and normalized in OPT_OUT_PHRASES


def inbound_phone_candidates(raw: str | None) -> list[str]:
    """Telefones possíveis para casar o remetente com o eleitor cadastrado.

    O WhatsApp informa muitos celulares brasileiros antigos SEM o nono dígito (55 + DDD + 8 dígitos), enquanto o
    cadastro guarda 55 + DDD + 9 dígitos — testamos as duas formas. Ordem = preferência.
    """
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return []
    out: list[str] = [digits]

    def add(value: str) -> None:
        if value not in out:
            out.append(value)

    normalized = normalize_br_phone(digits)
    if normalized:
        add(normalized)
    base = normalized or digits
    if base.startswith("55"):
        local = base[2:]
        if len(local) == 10 and local[2] in "6789":
            add(f"55{local[:2]}9{local[2:]}")
        if len(local) == 11 and local[2] == "9":
            add(f"55{local[:2]}{local[3:]}")
    return out


def canonical_inbound_phone(raw: str | None) -> str:
    """Forma canônica para guardar o remetente: celular brasileiro com nono dígito; senão, só dígitos."""
    digits = re.sub(r"\D", "", raw or "")
    normalized = normalize_br_phone(digits)
    if normalized:
        local = normalized[2:]
        if len(local) == 10 and local[2] in "6789":
            return f"55{local[:2]}9{local[2:]}"
        return normalized
    return digits
