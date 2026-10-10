"""Twilio — parceiro oficial da Meta (Business Solution Provider) para a WhatsApp Business Platform."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from collections.abc import Iterable
from urllib.parse import parse_qsl, quote, urlsplit

from ..types import (
    OutgoingMessage,
    ProviderDefinition,
    ProviderField,
    SendResult,
    TestResult,
    WebhookEvent,
    WebhookRequest,
)
from . import common

TWILIO_API = "https://api.twilio.com/2010-04-01"

# Erros comuns da Twilio (WhatsApp) em pt-BR
TWILIO_ERROR_MESSAGES: dict[int, str] = {
    20003: "Credenciais inválidas (Account SID ou Auth Token)",
    20404: "Recurso não encontrado na conta Twilio",
    20429: "Limite de requisições da Twilio atingido",
    21211: "Número de destino inválido",
    21606: "O número remetente não pertence a esta conta Twilio",
    21610: "O destinatário bloqueou mensagens deste remetente",
    21656: "Variáveis do template (ContentVariables) inválidas",
    30007: "Mensagem filtrada pela operadora/Meta",
    30008: "Erro desconhecido na entrega",
    63003: "O número de destino não usa WhatsApp",
    63007: "Remetente não habilitado para WhatsApp nesta conta Twilio",
    63016: "Fora da janela de 24h: use um template aprovado (Content SID HX…)",
    63018: "Limite de vazão do WhatsApp atingido",
    63024: "Destinatário inválido para mensagens de WhatsApp",
    63049: "A Meta não entregou esta mensagem de marketing para preservar a experiência do usuário",
}
RETRYABLE_TWILIO_CODES = frozenset({20429, 63018})


def describe_twilio_error(code, message: str | None = None) -> str:
    try:
        n = int(code)
    except (TypeError, ValueError):
        n = None
    text = (TWILIO_ERROR_MESSAGES.get(n) if n is not None else None) or message or "Erro informado pela Twilio"
    return common.truncate(f"{text} (código {n})" if n is not None else text, 300)


def twilio_address(phone: str | None) -> str:
    """"+55 (11) 98765-4321" ou "whatsapp:+5511..." → "whatsapp:+5511987654321"."""
    return "whatsapp:+" + common.digits_only(re.sub(r"^whatsapp:", "", phone or "", flags=re.IGNORECASE))


def build_twilio_params(message: OutgoingMessage, creds: dict) -> dict[str, str]:
    """Campos do POST /Messages.json (form-encoded)."""
    params: dict[str, str] = {
        "To": twilio_address(message.to),
        "From": twilio_address(creds.get("from_number")),
    }
    if creds.get("messaging_service_sid"):
        params["MessagingServiceSid"] = creds["messaging_service_sid"]
    if creds.get("status_callback_url"):
        params["StatusCallback"] = creds["status_callback_url"]

    template = message.template
    if template is not None and template.name.startswith("HX"):
        # Template aprovado via Content API da Twilio: variáveis {{1}}, {{2}}...
        params["ContentSid"] = template.name
        if template.parameters:
            params["ContentVariables"] = json.dumps(
                {str(i + 1): p for i, p in enumerate(template.parameters)}, ensure_ascii=False
            )
    else:
        if message.text:
            params["Body"] = message.text
        if message.media is not None:
            params["MediaUrl"] = message.media.url
    return params


# ------------------------------------------------------------------------------------------------ Assinatura


def compute_twilio_signature(auth_token: str, url: str, params: Iterable[tuple[str, str]]) -> str:
    """X-Twilio-Signature = base64(HMAC-SHA1(auth_token, url + chaves e valores ordenados concatenados))."""
    data = url + "".join(k + v for k, v in sorted(params))
    digest = hmac.new(auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def twilio_signature_urls(url: str) -> list[str]:
    """URLs candidatas à assinatura: a pública como recebida, com e sem a porta padrão explícita."""
    urls = [url]
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        explicit_port = parts.port
    except ValueError:
        return urls
    default_port = 443 if parts.scheme == "https" else 80
    netloc_host = f"[{host}]" if ":" in host else host
    if explicit_port is None:
        variant = parts._replace(netloc=f"{netloc_host}:{default_port}")
    elif explicit_port == default_port:
        variant = parts._replace(netloc=netloc_host)
    else:
        return urls
    urls.append(variant.geturl())
    return urls


def verify_twilio_signature(req: WebhookRequest, auth_token: str | None) -> bool:
    header = req.headers.get("x-twilio-signature")
    if not auth_token or not header:
        return False
    params = parse_qsl(req.raw_body.decode("utf-8", errors="replace"), keep_blank_values=True)
    return any(
        common.safe_equal(header.strip(), compute_twilio_signature(auth_token, url, params))
        for url in twilio_signature_urls(req.url)
    )


# ------------------------------------------------------------------------------------------------ Webhook

_STATUS_MAP = {"sent": "SENT", "delivered": "DELIVERED", "read": "READ", "failed": "FAILED", "undelivered": "FAILED"}


def parse_twilio_webhook_body(raw_body: bytes | str) -> list[WebhookEvent]:
    """Webhooks da Twilio (form-encoded): callbacks de status e mensagens recebidas."""
    text = raw_body.decode("utf-8", errors="replace") if isinstance(raw_body, bytes) else raw_body
    p = dict(parse_qsl(text, keep_blank_values=True))
    sid = p.get("MessageSid") or p.get("SmsSid") or ""
    status_raw = (p.get("MessageStatus") or p.get("SmsStatus") or "").lower()

    if status_raw == "received" or (not p.get("MessageStatus") and "Body" in p):
        sender = common.digits_only(re.sub(r"^whatsapp:", "", p.get("WaId") or p.get("From") or "", flags=re.IGNORECASE))
        if not sender:
            return []
        return [WebhookEvent(kind="inbound", from_phone=sender, body=p.get("Body") or p.get("ButtonText") or "")]

    status = _STATUS_MAP.get(status_raw)
    if not sid or not status:
        return []
    error = describe_twilio_error(p.get("ErrorCode"), p.get("ErrorMessage")) if status == "FAILED" else ""
    return [WebhookEvent(kind="status", provider_message_id=sid, status=status, error=error)]


# ------------------------------------------------------------------------------------------------ Provedor


class TwilioProvider:
    key = "TWILIO"

    def __init__(self, credentials: dict):
        self.creds = common.normalize_credentials(credentials)

    def _auth(self) -> tuple[str, str]:
        return self.creds.get("account_sid", ""), self.creds.get("auth_token", "")

    def send(self, message: OutgoingMessage) -> SendResult:
        sid, token = self._auth()
        if not (sid and token and self.creds.get("from_number")):
            return SendResult(ok=False, error="Credenciais da Twilio incompletas", retryable=False)
        if not common.is_valid_recipient(message.to):
            return SendResult(ok=False, error="Número de destino inválido", retryable=False)
        try:
            res = common.provider_request(
                "POST",
                f"{TWILIO_API}/Accounts/{quote(sid, safe='')}/Messages.json",
                auth=self._auth(),
                form=build_twilio_params(message, self.creds),
            )
        except Exception as exc:  # noqa: BLE001
            return common.send_failure_from_error(exc)
        data = res.data if isinstance(res.data, dict) else {}
        if res.ok and data.get("sid"):
            return SendResult(ok=True, provider_message_id=str(data["sid"]))
        code = data.get("code")
        try:
            code_int = int(code)
        except (TypeError, ValueError):
            code_int = None
        return SendResult(
            ok=False,
            error=describe_twilio_error(code, data.get("message") or f"Erro HTTP {res.status} da Twilio"),
            retryable=res.status == 429 or res.status >= 500 or (code_int in RETRYABLE_TWILIO_CODES),
        )

    def test_connection(self) -> TestResult:
        sid, token = self._auth()
        if not (sid and token):
            return TestResult(ok=False, message="Informe o Account SID e o Auth Token.")
        try:
            res = common.provider_request("GET", f"{TWILIO_API}/Accounts/{quote(sid, safe='')}.json", auth=self._auth())
        except Exception as exc:  # noqa: BLE001
            return TestResult(ok=False, message=common.check_failure_message(exc))
        data = res.data if isinstance(res.data, dict) else None
        if not res.ok or data is None:
            code = (data or {}).get("code") or (20003 if res.status == 401 else None)
            return TestResult(ok=False, message=describe_twilio_error(code, (data or {}).get("message") or f"Erro HTTP {res.status} da Twilio"))
        if data.get("status") and data["status"] != "active":
            return TestResult(ok=False, message=f'A conta Twilio está com status "{data["status"]}".')
        name = data.get("friendly_name") or sid
        return TestResult(ok=True, message=f"Conta Twilio ativa: {name}.", phone_number=self.creds.get("from_number", ""))


def _verify_signature(req: WebhookRequest, credentials: dict) -> bool:
    return verify_twilio_signature(req, common.normalize_credentials(credentials).get("auth_token"))


def _parse_webhook(req: WebhookRequest) -> list[WebhookEvent]:
    return parse_twilio_webhook_body(req.raw_body)


TWILIO = ProviderDefinition(
    key="TWILIO",
    label="Twilio",
    description=(
        "Parceiro oficial da Meta (BSP), cobrança em cartão e API simples. "
        "Para iniciar conversas use templates aprovados (Content SID HX…)."
    ),
    official=True,
    docs_url="https://www.twilio.com/docs/whatsapp",
    setup_steps=[
        "No Console da Twilio, ative o WhatsApp (Messaging › Senders › WhatsApp senders) e registre o número da "
        "campanha pelo fluxo de cadastro da Meta.",
        "Copie o Account SID e o Auth Token da página inicial do Console.",
        'No remetente de WhatsApp, em "Webhook URL for incoming messages", cole a URL de callback abaixo (método POST).',
        "Os status de entrega e leitura são configurados automaticamente em cada envio (StatusCallback).",
        "Crie os templates em Messaging › Content Template Builder, envie para aprovação do WhatsApp e use o "
        "Content SID (HX…) nos modelos de mensagem.",
    ],
    fields=[
        ProviderField(
            name="account_sid",
            label="Account SID",
            required=True,
            placeholder="AC…",
            help="Começa com AC e tem 34 caracteres.",
        ),
        ProviderField(
            name="auth_token",
            label="Auth Token",
            type="password",
            required=True,
            secret=True,
            help="Também usado para validar a assinatura dos webhooks.",
        ),
        ProviderField(
            name="from_number",
            label="Número remetente do WhatsApp",
            required=True,
            placeholder="+5511999999999",
            help="Número habilitado como remetente de WhatsApp na Twilio, no formato internacional (E.164).",
        ),
        ProviderField(
            name="messaging_service_sid",
            label="Messaging Service SID",
            placeholder="MG…",
            help="Opcional. Use se o remetente estiver em um Messaging Service.",
        ),
    ],
    requires_approved_template=True,
    create=lambda credentials: TwilioProvider(credentials),
    parse_webhook=_parse_webhook,
    verify_signature=_verify_signature,
)
