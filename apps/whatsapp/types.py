"""CONTRATO entre o módulo de provedores de WhatsApp (apps.whatsapp) e o de disparos (apps.messaging).
Não altere as assinaturas sem atualizar os dois lados.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol


@dataclass
class MediaAttachment:
    type: Literal["IMAGE", "DOCUMENT", "VIDEO"]
    url: str  # URL pública acessível pelo provedor
    filename: str = ""


@dataclass
class TemplateCall:
    """Template aprovado (API oficial da Meta / 360dialog / Twilio ContentSid). Mensagens iniciadas pela empresa
    fora da janela de 24h EXIGEM template aprovado. `parameters` = valores de {{1}}, {{2}}... na ordem."""

    name: str
    language: str = "pt_BR"
    parameters: list[str] = field(default_factory=list)


@dataclass
class OutgoingMessage:
    """Mensagem a enviar para UM destinatário."""

    to: str  # só dígitos, com DDI (ex.: 5511987654321)
    text: str  # texto final já renderizado (mensagem livre / legenda de mídia)
    media: MediaAttachment | None = None
    template: TemplateCall | None = None


@dataclass
class SendResult:
    ok: bool
    provider_message_id: str = ""  # id da mensagem no provedor (casa com os webhooks de status)
    error: str = ""
    retryable: bool = False  # vale tentar de novo (rate limit, 5xx, timeout)


@dataclass
class TestResult:
    ok: bool
    message: str
    phone_number: str = ""  # número/nome verificado no provedor, quando disponível

    __test__ = False  # evita que o pytest/unittest trate a classe como teste


@dataclass
class WebhookEvent:
    """Evento normalizado recebido pelo webhook.
    kind="status": provider_message_id + status ("SENT"|"DELIVERED"|"READ"|"FAILED") [+ error].
    kind="inbound": from_phone (só dígitos, com DDI) + body."""

    kind: Literal["status", "inbound"]
    provider_message_id: str = ""
    status: str = ""
    error: str = ""
    from_phone: str = ""
    body: str = ""
    timestamp: datetime | None = None


class WhatsAppProvider(Protocol):
    """Instância pronta para uso (credenciais já descriptografadas)."""

    key: str

    def send(self, message: OutgoingMessage) -> SendResult: ...

    def test_connection(self) -> TestResult: ...


@dataclass
class ProviderField:
    name: str
    label: str
    type: Literal["text", "password", "url"] = "text"
    required: bool = False
    placeholder: str = ""
    help: str = ""
    secret: bool = False  # segredos nunca voltam ao navegador (exibidos mascarados)


@dataclass
class WebhookRequest:
    """Requisição HTTP recebida no webhook, já lida."""

    method: str
    url: str  # URL pública completa (Twilio assina com ela)
    headers: Mapping[str, str]  # chaves em minúsculas
    raw_body: bytes
    query: Mapping[str, str] = field(default_factory=dict)


@dataclass
class WebhookResponse:
    status: int
    body: str
    content_type: str = "text/plain"


@dataclass
class ProviderDefinition:
    key: str
    label: str
    description: str
    official: bool  # provedor oficial/parceiro autorizado da Meta (Res. TSE 23.610/2019, art. 28, IV)
    setup_steps: list[str]
    fields: list[ProviderField]
    requires_approved_template: bool
    create: Callable[[dict], WhatsAppProvider]
    parse_webhook: Callable[[WebhookRequest], list[WebhookEvent]]
    docs_url: str = ""
    # GET de verificação (Meta). Retorna None se a requisição não for de verificação.
    handle_verification: Callable[[WebhookRequest, dict, str], WebhookResponse | None] | None = None
    # Valida a assinatura do webhook. Sem implementação = aceita.
    verify_signature: Callable[[WebhookRequest, dict], bool] | None = None
