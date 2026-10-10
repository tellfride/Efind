"""WhatsApp Cloud API — API oficial da Meta (WhatsApp Business Platform)."""

from __future__ import annotations

from urllib.parse import quote

from ..types import (
    OutgoingMessage,
    ProviderDefinition,
    ProviderField,
    SendResult,
    TestResult,
    WebhookEvent,
    WebhookRequest,
    WebhookResponse,
)
from . import common
from .cloud_api import (
    DEFAULT_GRAPH_API_VERSION,
    build_cloud_api_payload,
    describe_cloud_error,
    handle_cloud_verification,
    parse_cloud_api_send_response,
    parse_cloud_api_webhook_body,
    quality_label,
    verify_cloud_signature,
)


def graph_base_url(api_version: str | None) -> str:
    version = (api_version or "").strip() or DEFAULT_GRAPH_API_VERSION
    return f"https://graph.facebook.com/{quote(version, safe='')}"


class MetaCloudProvider:
    key = "META_CLOUD"

    def __init__(self, credentials: dict):
        self.creds = common.normalize_credentials(credentials)

    def _headers(self, json_body: bool = False) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.creds.get('access_token', '')}"}
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _complete(self) -> bool:
        return bool(self.creds.get("phone_number_id") and self.creds.get("access_token"))

    def send(self, message: OutgoingMessage) -> SendResult:
        if not self._complete():
            return SendResult(ok=False, error="Credenciais da Meta incompletas", retryable=False)
        if not common.is_valid_recipient(message.to):
            return SendResult(ok=False, error="Número de destino inválido", retryable=False)
        url = f"{graph_base_url(self.creds.get('api_version'))}/{quote(self.creds['phone_number_id'], safe='')}/messages"
        try:
            res = common.provider_request("POST", url, headers=self._headers(json_body=True), json_body=build_cloud_api_payload(message))
        except Exception as exc:  # noqa: BLE001
            return common.send_failure_from_error(exc)
        return parse_cloud_api_send_response(res.status, res.data)

    def test_connection(self) -> TestResult:
        if not self._complete():
            return TestResult(ok=False, message="Informe o ID do número e o token de acesso.")
        url = (
            f"{graph_base_url(self.creds.get('api_version'))}/{quote(self.creds['phone_number_id'], safe='')}"
            "?fields=display_phone_number,verified_name,quality_rating"
        )
        try:
            res = common.provider_request("GET", url, headers=self._headers())
        except Exception as exc:  # noqa: BLE001
            return TestResult(ok=False, message=common.check_failure_message(exc))
        data = res.data if isinstance(res.data, dict) else None
        if not res.ok or data is None or data.get("error"):
            message = describe_cloud_error(data.get("error") if data else None) or f"A Meta respondeu com erro HTTP {res.status}."
            return TestResult(ok=False, message=message)
        phone = str(data.get("display_phone_number") or "")
        name = str(data.get("verified_name") or "número verificado")
        parts = [f"Conectado à Meta: {name}{f' ({phone})' if phone else ''}"]
        if quality := quality_label(data.get("quality_rating")):
            parts.append(f"qualidade {quality}")
        return TestResult(ok=True, message=" · ".join(parts) + ".", phone_number=phone)


def _handle_verification(req: WebhookRequest, credentials: dict, webhook_token: str) -> WebhookResponse | None:
    return handle_cloud_verification(req, webhook_token)


def _verify_signature(req: WebhookRequest, credentials: dict) -> bool:
    secret = common.normalize_credentials(credentials).get("app_secret")
    return verify_cloud_signature(req.raw_body, req.headers.get("x-hub-signature-256"), secret)


def _parse_webhook(req: WebhookRequest) -> list[WebhookEvent]:
    return parse_cloud_api_webhook_body(req.raw_body)


META_CLOUD = ProviderDefinition(
    key="META_CLOUD",
    label="WhatsApp Cloud API (Meta)",
    description=(
        "API oficial do WhatsApp Business, hospedada pela própria Meta. Melhor custo e entregabilidade; "
        "exige um app no Meta for Developers e templates aprovados."
    ),
    official=True,
    docs_url="https://developers.facebook.com/docs/whatsapp/cloud-api/get-started",
    setup_steps=[
        "No Meta for Developers (developers.facebook.com), crie um app do tipo Empresa e adicione o produto WhatsApp.",
        "Em WhatsApp › Configuração da API, adicione e verifique o número de telefone da campanha. Copie o ID do número "
        "de telefone e o ID da conta do WhatsApp Business.",
        "No Gerenciador de Negócios, crie um Usuário do Sistema, atribua o app e a conta do WhatsApp e gere um token "
        "permanente com as permissões whatsapp_business_messaging e whatsapp_business_management.",
        'Em WhatsApp › Configuração, configure o webhook: cole a URL de callback e o token de verificação abaixo e assine o campo "messages".',
        "Copie a Chave secreta do app (Configurações do app › Básico) para validar a assinatura dos webhooks.",
        "No WhatsApp Manager, crie os templates de mensagem e aguarde a aprovação da Meta antes de disparar.",
    ],
    fields=[
        ProviderField(
            name="phone_number_id",
            label="ID do número de telefone",
            required=True,
            placeholder="123456789012345",
            help="Phone number ID, em WhatsApp › Configuração da API.",
        ),
        ProviderField(
            name="business_account_id",
            label="ID da conta do WhatsApp Business (WABA)",
            placeholder="109876543210987",
            help="Opcional. Ajuda a identificar a conta no Gerenciador de Negócios.",
        ),
        ProviderField(
            name="access_token",
            label="Token de acesso permanente",
            type="password",
            required=True,
            secret=True,
            placeholder="EAAG…",
            help="Token de Usuário do Sistema com whatsapp_business_messaging e whatsapp_business_management.",
        ),
        ProviderField(
            name="app_secret",
            label="Chave secreta do app (App Secret)",
            type="password",
            secret=True,
            help="Recomendado: valida a assinatura X-Hub-Signature-256 de cada webhook.",
        ),
        ProviderField(
            name="api_version",
            label="Versão da Graph API",
            placeholder=DEFAULT_GRAPH_API_VERSION,
            help=f"Deixe em branco para usar {DEFAULT_GRAPH_API_VERSION}.",
        ),
    ],
    requires_approved_template=True,
    create=lambda credentials: MetaCloudProvider(credentials),
    parse_webhook=_parse_webhook,
    handle_verification=_handle_verification,
    verify_signature=_verify_signature,
)
