"""Filtros e tags dos templates do módulo de mensagens: {% load messaging_tags %}."""

from __future__ import annotations

from django import template

from apps.core.constants import BroadcastStatus, MessageStatus, label_of
from apps.core.templatetags.ui import badge as _badge

from ..display import BROADCAST_TONES, MESSAGE_TONES
from ..whatsapp_format import format_whatsapp_html, plain_excerpt

register = template.Library()


@register.filter
def whatsapp(value):
    """Texto com *negrito*, _itálico_ e ~tachado~ → HTML seguro (o texto é escapado)."""
    return format_whatsapp_html(value)


@register.filter
def excerpt(value, limit=160):
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 160
    return plain_excerpt(value, limit)


@register.simple_tag
def broadcast_badge(status, css=""):
    return _badge(label_of(BroadcastStatus, status), BROADCAST_TONES.get(status, "gray"), css)


@register.simple_tag
def message_badge(status, css=""):
    return _badge(label_of(MessageStatus, status), MESSAGE_TONES.get(status, "gray"), css)
