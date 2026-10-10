"""Operações de conexão usadas pelas views (sem dependência de request). Toda função recebe o `campaign_id` e
só enxerga conexões dessa campanha."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from apps.core.constants import BroadcastStatus, ConnectionStatus
from apps.core.crypto import mask_secret

from .credentials import split_credentials
from .models import WhatsAppConnection
from .registry import decrypt_credentials, get_provider_definition, provider_for_connection, webhook_url_for
from .types import OutgoingMessage, SendResult, TemplateCall, TestResult

logger = logging.getLogger(__name__)

# Disparos que impedem excluir a conexão
ACTIVE_BROADCAST_STATUSES = (BroadcastStatus.RUNNING, BroadcastStatus.SCHEDULED, BroadcastStatus.PAUSED)
MAX_CONNECTIONS_PER_CAMPAIGN = 20
UNREADABLE_CREDENTIALS_MESSAGE = "Não foi possível ler as credenciais salvas. Edite a conexão e informe-as novamente."

STATUS_TONES = {
    ConnectionStatus.CONNECTED: "green",
    ConnectionStatus.ERROR: "red",
    ConnectionStatus.DRAFT: "gray",
    ConnectionStatus.DISABLED: "yellow",
}

# Ícones (Lucide) de cada provedor no assistente
PROVIDER_ICONS = {"META_CLOUD": "badge-check", "DIALOG360": "handshake", "TWILIO": "phone-call", "SANDBOX": "construction"}


def campaign_connections(campaign_id):
    return WhatsAppConnection.objects.filter(campaign_id=campaign_id)


def get_campaign_connection(campaign_id, pk) -> WhatsAppConnection | None:
    """Uma conexão pelo id, somente se pertencer à campanha (senão None). Ids malformados também dão None."""
    try:
        return campaign_connections(campaign_id).filter(pk=pk).first()
    except (ValueError, TypeError, ValidationError):
        return None


def active_broadcast_counts(campaign_id, connection_ids: Iterable) -> dict:
    """{connection_id: nº de disparos em andamento, agendados ou pausados} (uma consulta só)."""
    from apps.messaging.models import Broadcast

    rows = (
        Broadcast.objects.filter(campaign_id=campaign_id, connection_id__in=list(connection_ids), status__in=ACTIVE_BROADCAST_STATUSES)
        .values("connection_id")
        .annotate(n=Count("id"))
    )
    return {r["connection_id"]: r["n"] for r in rows}


def count_active_broadcasts(campaign_id, connection_id) -> int:
    return active_broadcast_counts(campaign_id, [connection_id]).get(connection_id, 0)


def decorate_connections(connections: Iterable[WhatsAppConnection], campaign_id) -> list[WhatsAppConnection]:
    """Acrescenta aos objetos os dados de exibição (provedor, tom do status, disparos ativos)."""
    items = list(connections)
    counts = active_broadcast_counts(campaign_id, [c.pk for c in items]) if items else {}
    for conn in items:
        conn.provider_def = get_provider_definition(conn.provider)
        conn.status_tone = STATUS_TONES.get(conn.status, "gray")
        conn.active_broadcasts = counts.get(conn.pk, 0)
    return items


def ensure_default_connection(campaign_id) -> None:
    """Garante uma conexão padrão na campanha: se nenhuma ativa estiver marcada, promove a primeira conectada
    (ou, na falta, a primeira não desativada)."""
    qs = campaign_connections(campaign_id)
    if qs.filter(is_default=True).exclude(status=ConnectionStatus.DISABLED).exists():
        return
    candidate = (
        qs.filter(status=ConnectionStatus.CONNECTED).order_by("created_at").first()
        or qs.exclude(status=ConnectionStatus.DISABLED).order_by("created_at").first()
    )
    if candidate is not None:
        set_default_connection(candidate)


def set_default_connection(conn: WhatsAppConnection) -> None:
    now = timezone.now()
    with transaction.atomic():
        campaign_connections(conn.campaign_id).filter(is_default=True).exclude(pk=conn.pk).update(is_default=False, updated_at=now)
        campaign_connections(conn.campaign_id).filter(pk=conn.pk).update(is_default=True, updated_at=now)
    conn.is_default = True


def run_connection_test(conn: WhatsAppConnection, *, keep_disabled: bool = False) -> tuple[WhatsAppConnection, TestResult]:
    """Testa a conexão no provedor e grava o resultado: CONNECTED quando passa, ERROR (com last_error) quando falha.
    Com keep_disabled, uma conexão desativada continua desativada."""
    try:
        result = provider_for_connection(conn, with_events=False).test_connection()
    except Exception as exc:  # noqa: BLE001 - qualquer falha vira um resultado de teste, sem vazar detalhes
        logger.error("Falha ao testar conexão de WhatsApp (%s): %s", conn.provider, type(exc).__name__)
        result = TestResult(ok=False, message=UNREADABLE_CREDENTIALS_MESSAGE)

    if keep_disabled and conn.status == ConnectionStatus.DISABLED:
        status = ConnectionStatus.DISABLED
    else:
        status = ConnectionStatus.CONNECTED if result.ok else ConnectionStatus.ERROR
    fields = {
        "status": status,
        "last_tested_at": timezone.now(),
        "last_error": "" if result.ok else result.message[:300],
        "updated_at": timezone.now(),
    }
    if result.ok and result.phone_number and not conn.phone_number:
        fields["phone_number"] = result.phone_number[:30]
    campaign_connections(conn.campaign_id).filter(pk=conn.pk).update(**fields)
    if status == ConnectionStatus.CONNECTED:
        ensure_default_connection(conn.campaign_id)
    conn.refresh_from_db()
    return conn, result


def send_test_message(conn: WhatsAppConnection, to: str, text: str, use_template: bool = False) -> SendResult:
    """Envia uma mensagem avulsa de teste (fora de disparos; o simulador não gera eventos para ela)."""
    if use_template:
        message = OutgoingMessage(to=to, text="", template=TemplateCall(name="hello_world", language="en_US", parameters=[]))
    else:
        message = OutgoingMessage(to=to, text=text)
    try:
        return provider_for_connection(conn, with_events=False).send(message)
    except Exception as exc:  # noqa: BLE001
        logger.error("Falha ao enviar mensagem de teste (%s): %s", conn.provider, type(exc).__name__)
        return SendResult(ok=False, error=UNREADABLE_CREDENTIALS_MESSAGE)


def read_credentials(conn: WhatsAppConnection) -> tuple[dict[str, str], bool]:
    """(credenciais descriptografadas, ilegível?). Se a chave de criptografia mudou, devolve ({}, True)."""
    try:
        return decrypt_credentials(conn.credentials), False
    except Exception as exc:  # noqa: BLE001
        logger.error("Credenciais de WhatsApp ilegíveis (%s): %s", conn.provider, type(exc).__name__)
        return {}, True


def connection_summary(conn: WhatsAppConnection) -> dict:
    """Dados de uma conexão para a interface: segredos sempre mascarados, nunca em claro."""
    definition = get_provider_definition(conn.provider)
    credentials, unreadable = read_credentials(conn)
    values, masked = split_credentials(definition.fields if definition else [], credentials)
    return {
        "values": values,
        "secrets": {name: mask_secret(credentials[name]) for name in masked},
        "unreadable": unreadable,
        "webhook_url": webhook_url_for(conn.webhook_token),
    }
