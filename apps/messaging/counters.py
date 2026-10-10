"""Contadores dos disparos a partir das mensagens. Sem dependência de request (usado pelo worker, pelo processador da
fila, pelas ações das telas e pelo webhook do WhatsApp — contrato: `refresh_broadcast_counters(broadcast_id)`)."""

from __future__ import annotations

from django.db.models import Count
from django.utils import timezone

from apps.core.constants import BroadcastStatus

from .logic import Counters, counters_from_groups, should_complete


def load_status_counts(broadcast_id) -> Counters:
    """Contagem atual das mensagens do disparo por status."""
    from .models import BroadcastMessage

    rows = (
        BroadcastMessage.objects.filter(broadcast_id=broadcast_id)
        .order_by()
        .values_list("status")
        .annotate(n=Count("id"))
    )
    return counters_from_groups(list(rows))


def recompute_broadcast_counters(broadcast_id) -> bool:
    """Recalcula os contadores e conclui o disparo quando não há mais PENDING/SENDING.

    Retorna True se o disparo foi concluído nesta chamada.
    """
    from .models import Broadcast

    row = Broadcast.objects.filter(pk=broadcast_id).values("status").first()
    if row is None:
        return False
    counters = load_status_counts(broadcast_id)
    now = timezone.now()
    data = {
        "sent_count": counters.sent,
        "delivered_count": counters.delivered,
        "read_count": counters.read,
        "failed_count": counters.failed,
        "updated_at": now,
    }
    if should_complete(row["status"], counters.pending, counters.sending):
        # Atualização condicional: se alguém pausou/cancelou nesse meio tempo, não sobrescreve o status
        done = Broadcast.objects.filter(pk=broadcast_id, status=BroadcastStatus.RUNNING).update(
            **data, status=BroadcastStatus.COMPLETED, finished_at=now
        )
        if done == 1:
            return True
    Broadcast.objects.filter(pk=broadcast_id).update(**data)
    return False


def refresh_broadcast_counters(broadcast_id) -> None:
    """Recalcula sent/delivered/read/failed_count do disparo a partir dos status de BroadcastMessage e marca
    COMPLETED (finished_at) quando não houver mais mensagens PENDING/SENDING e o disparo estiver RUNNING."""
    recompute_broadcast_counters(broadcast_id)
