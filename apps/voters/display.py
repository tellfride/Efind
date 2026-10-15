"""Apresentação de apoiadores nas telas (rótulos, tons de badge, links): sem consultas ao banco."""

from __future__ import annotations

from apps.core.constants import GeoStatus, MessageStatus, SupportLevel, VoterSource, label_of
from apps.core.phone import whatsapp_link

from .utils import WHATSAPP_STATUS_LABELS, WHATSAPP_STATUS_TONES, whatsapp_status_of

SUPPORT_TONES = {
    SupportLevel.APOIADOR.value: "green",
    SupportLevel.SIMPATIZANTE.value: "blue",
    SupportLevel.INDECISO.value: "yellow",
    SupportLevel.OPOSITOR.value: "red",
}

GEO_TONES = {
    GeoStatus.OK.value: "green",
    GeoStatus.APPROXIMATE.value: "blue",
    GeoStatus.PENDING.value: "gray",
    GeoStatus.FAILED.value: "red",
}

MESSAGE_STATUS_TONES = {
    MessageStatus.PENDING.value: "gray",
    MessageStatus.SENDING.value: "blue",
    MessageStatus.SENT.value: "blue",
    MessageStatus.DELIVERED.value: "green",
    MessageStatus.READ.value: "green",
    MessageStatus.FAILED.value: "red",
    MessageStatus.SKIPPED.value: "yellow",
}


def decorate_voter(voter):
    """Acrescenta atributos de exibição ao apoiador (situação do WhatsApp, apoio, link wa.me, origem)."""
    status = whatsapp_status_of(voter)
    voter.wa_status = status
    voter.wa_label = WHATSAPP_STATUS_LABELS[status]
    voter.wa_tone = WHATSAPP_STATUS_TONES[status]
    voter.support_label = label_of(SupportLevel, voter.support_level) if voter.support_level else ""
    voter.support_tone = SUPPORT_TONES.get(voter.support_level, "gray")
    voter.source_label = label_of(VoterSource, voter.source)
    voter.geo_label = label_of(GeoStatus, voter.geo_status)
    voter.geo_tone = GEO_TONES.get(voter.geo_status, "gray")
    voter.wa_url = whatsapp_link(voter.phone) if voter.phone else ""
    return voter


def decorate_voters(voters):
    for voter in voters:
        decorate_voter(voter)
    return voters


def message_status_tone(status: str) -> str:
    return MESSAGE_STATUS_TONES.get(status, "gray")
