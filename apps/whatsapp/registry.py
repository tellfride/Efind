"""Registro dos provedores de WhatsApp. Contrato usado pelo módulo de disparos e pelo worker: mantenha os nomes
PROVIDERS, get_provider_definition, provider_for_connection e get_default_connection.
Sem imports de request/messages/decorators (o worker usa este módulo)."""

from __future__ import annotations

from apps.core.constants import ConnectionStatus
from apps.core.crypto import decrypt_json
from apps.core.qr import app_url

from .models import WhatsAppConnection
from .providers import common
from .providers.dialog360 import DIALOG360
from .providers.meta_cloud import META_CLOUD
from .providers.sandbox import SANDBOX
from .providers.twilio import TWILIO
from .types import ProviderDefinition, WhatsAppProvider

# Todos os provedores disponíveis (ordem de exibição). Somente API oficial, parceiros oficiais da Meta e o simulador.
PROVIDERS: list[ProviderDefinition] = [META_CLOUD, DIALOG360, TWILIO, SANDBOX]


def get_provider_definition(key: str) -> ProviderDefinition | None:
    return next((p for p in PROVIDERS if p.key == key), None)


def webhook_url_for(webhook_token: str) -> str:
    """URL pública (callback) do webhook de uma conexão."""
    return app_url(f"/api/webhooks/whatsapp/{webhook_token}/")


def decrypt_credentials(encrypted: str) -> dict[str, str]:
    """Credenciais salvas, descriptografadas, com chaves em snake_case e valores string.
    Lança erro se a chave de criptografia não confere ou o conteúdo é inválido."""
    data = decrypt_json(encrypted)
    if not isinstance(data, dict):
        raise ValueError("Credenciais em formato inválido")
    return common.normalize_credentials(data)


def provider_for_connection(connection: WhatsAppConnection, *, with_events: bool = True) -> WhatsAppProvider:
    """Descriptografa as credenciais da conexão e cria a instância do provedor.

    Injeta `status_callback_url` (Twilio) e `__connection_id`/`__campaign_id` (o simulador usa para gerar eventos de
    entrega/leitura). `with_events=False` omite os ids: mensagens avulsas (teste) não geram eventos simulados.
    """
    definition = get_provider_definition(connection.provider)
    if definition is None:
        raise ValueError(f"Provedor de WhatsApp desconhecido: {connection.provider}")
    credentials = decrypt_credentials(connection.credentials)
    if connection.webhook_token:
        credentials["status_callback_url"] = webhook_url_for(connection.webhook_token)
    if with_events:
        credentials["__connection_id"] = str(connection.pk)
        credentials["__campaign_id"] = str(connection.campaign_id)
    return definition.create(credentials)


def get_default_connection(campaign_id) -> WhatsAppConnection | None:
    """Conexão padrão ativa (status CONNECTED) da campanha; senão a primeira conectada; senão None."""
    connected = WhatsAppConnection.objects.filter(campaign_id=campaign_id, status=ConnectionStatus.CONNECTED)
    return connected.filter(is_default=True).order_by("created_at").first() or connected.order_by("created_at").first()
