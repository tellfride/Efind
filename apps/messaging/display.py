"""Dados de exibição dos disparos (tons de status, contadores, taxas). Sem request."""

from __future__ import annotations

from collections.abc import Iterable

from apps.core.constants import BroadcastStatus, MessageStatus, TemplateType, label_of

from .logic import ACTIVE_BROADCAST_STATUSES, broadcast_rates, counters_from_groups, percent
from .queries import message_status_counts

BROADCAST_TONES = {
    BroadcastStatus.DRAFT: "gray",
    BroadcastStatus.SCHEDULED: "blue",
    BroadcastStatus.RUNNING: "brand",
    BroadcastStatus.PAUSED: "yellow",
    BroadcastStatus.COMPLETED: "green",
    BroadcastStatus.CANCELLED: "gray",
    BroadcastStatus.FAILED: "red",
}

PROGRESS_TONES = {
    BroadcastStatus.COMPLETED: "green",
    BroadcastStatus.PAUSED: "yellow",
    BroadcastStatus.CANCELLED: "yellow",
    BroadcastStatus.FAILED: "red",
}

MESSAGE_TONES = {
    MessageStatus.PENDING: "gray",
    MessageStatus.SENDING: "brand",
    MessageStatus.SENT: "blue",
    MessageStatus.DELIVERED: "green",
    MessageStatus.READ: "purple",
    MessageStatus.FAILED: "red",
    MessageStatus.SKIPPED: "yellow",
}

MEDIA_LABELS = {
    TemplateType.IMAGE: "Imagem",
    TemplateType.DOCUMENT: "Documento (PDF)",
    TemplateType.VIDEO: "Vídeo",
}


def decorate_broadcasts(items: Iterable) -> list:
    """Acrescenta aos disparos os contadores ao vivo (uma consulta para todos) e as taxas."""
    items = list(items)
    counts = message_status_counts([b.pk for b in items]) if items else {}
    for b in items:
        c = counters_from_groups(counts.get(b.pk, {}))
        total = c.total or b.total_recipients
        b.stats = c
        b.total_shown = total
        b.progress_pct = percent(c.processed, total)
        b.delivery_rate, b.read_rate = broadcast_rates(c.sent, c.delivered, c.read)
        b.status_tone = BROADCAST_TONES.get(b.status, "gray")
        b.progress_tone = PROGRESS_TONES.get(b.status, "brand")
        b.is_live = b.status in ACTIVE_BROADCAST_STATUSES
    return items


def status_options(statuses=BroadcastStatus) -> list[tuple[str, str]]:
    return [(value, label) for value, label in statuses.choices]


def message_status_options() -> list[tuple[str, str]]:
    return [(value, label) for value, label in MessageStatus.choices]


def broadcast_status_label(status: str) -> str:
    return label_of(BroadcastStatus, status)


def mask_phone(phone: str) -> str:
    """5511987654321 → 5511•••••21 (para quem não pode ver o número completo)."""
    digits = phone or ""
    if len(digits) < 8:
        return "••••••"
    return f"{digits[:4]}•••••{digits[-2:]}"
