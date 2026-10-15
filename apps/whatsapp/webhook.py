"""Aplica os eventos normalizados dos webhooks: status das mensagens de disparo e mensagens recebidas (histórico +
descadastro por "SAIR"). Sem dependência de request: usado pela view do webhook e pelo simulador (inclusive no worker).

Toda busca é restrita à campanha da conexão: um provedor nunca altera mensagens ou apoiadores de outra campanha.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.auditlog.service import audit
from apps.core.constants import MessageStatus
from apps.messaging import counters
from apps.messaging.models import BroadcastMessage
from apps.voters.models import Voter

from .models import InboundMessage
from .rules import (
    build_status_update,
    canonical_inbound_phone,
    inbound_phone_candidates,
    is_opt_out_message,
    status_rank,
)
from .types import WebhookEvent

logger = logging.getLogger(__name__)

OPT_OUT_ERROR = "Descadastrado"
INBOUND_BODY_MAX = 4096


@dataclass
class ApplyWebhookResult:
    matched: int = 0  # eventos de status cuja mensagem foi encontrada na campanha
    updated: int = 0  # mensagens cujo status mudou
    inbound: int = 0  # mensagens recebidas registradas
    opt_outs: int = 0  # apoiadores descadastrados nesta chamada
    touched_broadcasts: set = field(default_factory=set)


def _apply_status(campaign_id, event: WebhookEvent, touched: set) -> tuple[bool, bool]:
    """(encontrou a mensagem, mudou o status)."""
    provider_id = (event.provider_message_id or "").strip()
    if not provider_id:  # nunca casar com mensagens que ainda não têm id no provedor
        return False, False
    # Até duas tentativas: a atualização é condicional ao status lido (webhooks simultâneos do mesmo id)
    for _ in range(2):
        row = (
            BroadcastMessage.objects.filter(campaign_id=campaign_id, provider_message_id=provider_id)
            .values("pk", "broadcast_id", "status", "sent_at", "delivered_at", "read_at")
            .first()
        )
        if row is None:
            return False, False
        data = build_status_update(row, event.status, error=event.error, timestamp=event.timestamp)
        if data is None:
            return True, False
        changed = BroadcastMessage.objects.filter(pk=row["pk"], campaign_id=campaign_id, status=row["status"]).update(
            **data, updated_at=timezone.now()
        )
        if changed:
            touched.add(row["broadcast_id"])
            return True, True
    return True, False


def _find_voter(campaign_id, candidates: list[str]):
    voters = {v.phone: v for v in Voter.objects.filter(campaign_id=campaign_id, phone__in=candidates)}
    for phone in candidates:  # candidates está em ordem de preferência
        if phone in voters:
            return voters[phone]
    return None


def _apply_inbound(connection, event: WebhookEvent, touched: set) -> tuple[bool, bool]:
    """(registrou a mensagem, descadastrou o apoiador)."""
    candidates = inbound_phone_candidates(event.from_phone)
    if not candidates:
        return False, False
    campaign_id = connection.campaign_id
    voter = _find_voter(campaign_id, candidates)
    is_opt_out = is_opt_out_message(event.body)

    with transaction.atomic():
        InboundMessage.objects.create(
            campaign_id=campaign_id,
            connection_id=connection.id,
            from_phone=(voter.phone if voter else canonical_inbound_phone(event.from_phone))[:20],
            body=(event.body or "")[:INBOUND_BODY_MAX],
            voter=voter,
            is_opt_out=is_opt_out,
        )
        if not is_opt_out or voter is None:
            return True, False

        now = timezone.now()
        newly_opted_out = Voter.objects.filter(pk=voter.pk, campaign_id=campaign_id, opt_out_at__isnull=True).update(
            opt_out_at=now, updated_at=now
        )
        pending = BroadcastMessage.objects.filter(campaign_id=campaign_id, voter_id=voter.pk, status=MessageStatus.PENDING)
        touched.update(pending.values_list("broadcast_id", flat=True).distinct())
        pending.update(status=MessageStatus.SKIPPED, error=OPT_OUT_ERROR, updated_at=now)

    if newly_opted_out:
        # Auditoria sem dados pessoais (o webhook não tem usuário logado nem request)
        audit(
            "voter.opt_out",
            campaign_id=campaign_id,
            entity="Voter",
            entity_id=voter.pk,
            details={"source": "whatsapp", "connection_id": str(connection.id)},
        )
    return True, bool(newly_opted_out)


def apply_webhook_events(connection: Any, events: list[WebhookEvent]) -> ApplyWebhookResult:
    """Aplica eventos de webhook de uma conexão (qualquer objeto com `id` e `campaign_id`)."""
    result = ApplyWebhookResult()
    touched: set = set()
    campaign_id = connection.campaign_id

    statuses = sorted((e for e in events if e.kind == "status"), key=lambda e: status_rank(e.status))
    for event in statuses:
        matched, updated = _apply_status(campaign_id, event, touched)
        result.matched += int(matched)
        result.updated += int(updated)

    for event in events:
        if event.kind != "inbound":
            continue
        recorded, opted_out = _apply_inbound(connection, event, touched)
        result.inbound += int(recorded)
        result.opt_outs += int(opted_out)

    result.touched_broadcasts = touched
    for broadcast_id in touched:
        try:
            counters.refresh_broadcast_counters(broadcast_id)
        except Exception as exc:  # noqa: BLE001 - contadores não podem derrubar o webhook
            logger.error("Falha ao atualizar contadores do disparo: %s", type(exc).__name__)
    return result
