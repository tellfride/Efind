"""360dialog — parceiro oficial da Meta (Business Solution Provider). Usa o formato da Cloud API."""

from __future__ import annotations

from urllib.parse import urlsplit

from ..types import OutgoingMessage, ProviderDefinition, ProviderField, SendResult, TestResult, WebhookEvent, WebhookRequest
from . import common
from .cloud_api import build_cloud_api_payload, parse_cloud_api_send_response, parse_cloud_api_webhook_body

DIALOG360_DEFAULT_BASE_URL = "https://waba-v2.360dialog.io"
# A chave de API só é enviada a hosts da própria 360dialog (evita SSRF / vazamento da chave)
DIALOG360_ALLOWED_DOMAINS = ("360dialog.io", "360dialog.com")


def is_allowed_dialog360_url(url: str) -> bool:
    """https e host da própria 360dialog (domínio ou subdomínio), sem credenciais embutidas na URL."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        parts.port  # noqa: B018 - valida a porta (levanta ValueError se inválida)
    except ValueError:
        return False
    if parts.scheme != "https" or parts.username or parts.password:
        return False
    return any(host == d or host.endswith("." + d) for d in DIALOG360_ALLOWED_DOMAINS)


def dialog360_base_url(creds: dict) -> str:
    """URL base configurada; qualquer endereço fora da 360dialog é ignorado (usa a API de produção)."""
    configured = (creds.get("base_url") or "").strip().rstrip("/")
    return configured if configured and is_allowed_dialog360_url(configured) else DIALOG360_DEFAULT_BASE_URL


def _error_message(status: int, data) -> str:
    if status in (401, 403):
        return "Chave de API (D360-API-KEY) inválida ou sem permissão."
    d = data if isinstance(data, dict) else {}
    error = d.get("error") if isinstance(d.get("error"), dict) else {}
    meta = d.get("meta") if isinstance(d.get("meta"), dict) else {}
    errors = d.get("errors") if isinstance(d.get("errors"), list) and d.get("errors") else [{}]
    first = errors[0] if isinstance(errors[0], dict) else {}
    message = error.get("message") or meta.get("developer_message") or first.get("details") or first.get("title")
    return common.truncate(str(message), 300) if message else f"A 360dialog respondeu com erro HTTP {status}."


class Dialog360Provider:
    key = "DIALOG360"

    def __init__(self, credentials: dict):
        self.creds = common.normalize_credentials(credentials)

    def _headers(self, json_body: bool = False) -> dict[str, str]:
        headers = {"D360-API-KEY": self.creds.get("api_key", "")}
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def send(self, message: OutgoingMessage) -> SendResult:
        if not self.creds.get("api_key"):
            return SendResult(ok=False, error="Chave de API da 360dialog não configurada", retryable=False)
        if not common.is_valid_recipient(message.to):
            return SendResult(ok=False, error="Número de destino inválido", retryable=False)
        try:
            res = common.provider_request(
                "POST",
                f"{dialog360_base_url(self.creds)}/messages",
                headers=self._headers(json_body=True),
                json_body=build_cloud_api_payload(message),
            )
        except Exception as exc:  # noqa: BLE001
            return common.send_failure_from_error(exc)
        return parse_cloud_api_send_response(res.status, res.data)

    def test_connection(self) -> TestResult:
        if not self.creds.get("api_key"):
            return TestResult(ok=False, message="Informe a chave de API da 360dialog.")
        try:
            res = common.provider_request("GET", f"{dialog360_base_url(self.creds)}/v1/configs/webhook", headers=self._headers())
        except Exception as exc:  # noqa: BLE001
            return TestResult(ok=False, message=common.check_failure_message(exc))
        if not res.ok:
            return TestResult(ok=False, message=_error_message(res.status, res.data))
        url = res.data.get("url") if isinstance(res.data, dict) else None
        message = (
            "Chave de API válida. Webhook configurado na 360dialog."
            if url
            else "Chave de API válida. Nenhum webhook registrado ainda."
        )
        return TestResult(ok=True, message=message)


def register_webhook(credentials: dict, url: str) -> tuple[bool, str]:
    """Registra a URL de webhook do E-Find na 360dialog (POST /v1/configs/webhook)."""
    creds = common.normalize_credentials(credentials)
    if not creds.get("api_key"):
        return False, "Chave de API da 360dialog não configurada."
    try:
        res = common.provider_request(
            "POST",
            f"{dialog360_base_url(creds)}/v1/configs/webhook",
            headers={"D360-API-KEY": creds["api_key"], "Content-Type": "application/json"},
            json_body={"url": url},
        )
    except Exception as exc:  # noqa: BLE001
        return False, common.check_failure_message(exc)
    if not res.ok:
        return False, _error_message(res.status, res.data)
    return True, "Webhook registrado na 360dialog."


def _parse_webhook(req: WebhookRequest) -> list[WebhookEvent]:
    return parse_cloud_api_webhook_body(req.raw_body)


DIALOG360 = ProviderDefinition(
    key="DIALOG360",
    label="360dialog",
    description=(
        "Parceiro oficial da Meta (BSP) com painel próprio e suporte em português. "
        "Mesmo formato da Cloud API; exige templates aprovados."
    ),
    official=True,
    docs_url="https://docs.360dialog.com/docs/waba-messaging/messaging",
    setup_steps=[
        "Crie sua conta no 360dialog Hub (hub.360dialog.com) e conecte o número da campanha à WhatsApp Business Platform.",
        "No Hub, gere a chave de API (D360-API-KEY) do número e cole no passo anterior.",
        'Registre o webhook: use o botão "Registrar webhook automaticamente" ou cole a URL de callback abaixo na '
        "configuração de webhook do número no 360dialog Hub.",
        "Crie os templates de mensagem no Hub e aguarde a aprovação da Meta antes de disparar.",
    ],
    fields=[
        ProviderField(
            name="api_key",
            label="Chave de API (D360-API-KEY)",
            type="password",
            required=True,
            secret=True,
            help="Gerada no 360dialog Hub para o número conectado.",
        ),
        ProviderField(
            name="base_url",
            label="URL base da API",
            type="url",
            placeholder=DIALOG360_DEFAULT_BASE_URL,
            help="Deixe em branco para usar a API de produção (v2). Aceita apenas endereços https da 360dialog.",
        ),
    ],
    requires_approved_template=True,
    create=lambda credentials: Dialog360Provider(credentials),
    parse_webhook=_parse_webhook,
    # Sem handshake de verificação e sem assinatura: a URL secreta (token aleatório) autentica o webhook.
)
