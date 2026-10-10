"""Formato da WhatsApp Cloud API (Meta), compartilhado pela Meta e pela 360dialog: montagem do corpo de envio,
leitura de respostas/erros, webhooks, verificação (handshake) e assinatura. Funções puras (sem banco, sem rede)."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any

from ..types import OutgoingMessage, SendResult, WebhookEvent, WebhookRequest, WebhookResponse
from .common import digits_only, safe_equal, truncate, unix_to_datetime

DEFAULT_GRAPH_API_VERSION = "v21.0"

# Códigos de erro da Meta que indicam limite de taxa/vazão ou falha transitória (vale tentar de novo mais tarde)
RETRYABLE_CLOUD_ERROR_CODES = frozenset({1, 2, 4, 130429, 131048, 131056, 80007})

# Mensagens amigáveis para os erros mais comuns da Cloud API
CLOUD_ERROR_MESSAGES: dict[int, str] = {
    0: "Falha de autenticação na API da Meta",
    4: "Limite de chamadas do app atingido",
    100: "Parâmetro inválido na requisição",
    190: "Token de acesso inválido ou expirado",
    200: "Permissão insuficiente no token de acesso",
    368: "Conta temporariamente bloqueada por violação de políticas",
    130429: "Limite de vazão da API atingido",
    130472: "Número do destinatário faz parte de um experimento da Meta (mensagem não entregue)",
    131026: "Mensagem não entregável (o número não usa WhatsApp ou não aceitou os termos)",
    131030: "Número do destinatário não está na lista de números de teste permitidos",
    131031: "Conta do WhatsApp Business bloqueada ou restrita",
    131042: "Problema de pagamento na conta do WhatsApp Business",
    131047: "Mais de 24h desde a última mensagem do contato: é preciso usar um template aprovado",
    131048: "Limite de envio atingido por denúncias de spam (qualidade do número)",
    131049: "A Meta não entregou esta mensagem de marketing para preservar a experiência do usuário",
    131050: "O destinatário optou por não receber mensagens de marketing",
    131051: "Tipo de mensagem não suportado",
    131053: "Falha ao enviar a mídia (verifique se a URL é pública)",
    131056: "Muitas mensagens para o mesmo destinatário em pouco tempo",
    132000: "Quantidade de parâmetros não confere com o template aprovado",
    132001: "Template inexistente ou não aprovado neste idioma",
    132005: "Texto do template ficou longo demais após preencher os parâmetros",
    132007: "O conteúdo viola a política de formatação do template",
    132012: "Formato dos parâmetros não confere com o template aprovado",
    132015: "Template pausado por baixa qualidade",
    132016: "Template desativado por baixa qualidade",
    133010: "Número de telefone não registrado na Cloud API",
    80007: "Limite de taxa da conta do WhatsApp Business atingido",
}

QUALITY_LABELS = {"GREEN": "alta", "YELLOW": "média", "RED": "baixa", "UNKNOWN": "ainda não avaliada"}

_MEDIA_KIND = {"IMAGE": "image", "VIDEO": "video", "DOCUMENT": "document"}


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def describe_cloud_error(err: Any) -> str | None:
    """Descreve um erro da Cloud API em pt-BR (mensagem amigável quando conhecida + código)."""
    if not isinstance(err, dict):
        return None
    code = _as_int(err.get("code"))
    friendly = CLOUD_ERROR_MESSAGES.get(code) if code is not None else None
    error_data = err.get("error_data") if isinstance(err.get("error_data"), dict) else {}
    raw = friendly or err.get("title") or error_data.get("details") or err.get("details") or err.get("message")
    if not raw:
        return f"Erro {code} do provedor" if code is not None else None
    text = f"{raw} (código {code})" if code is not None else str(raw)
    return truncate(text, 300)


def sanitize_template_param(value: str | None) -> str:
    """Parâmetros de template não aceitam quebras de linha, tabs nem mais de 4 espaços seguidos."""
    v = re.sub(r"[\r\n\t]+", " ", value or "")
    v = re.sub(r" {4,}", "   ", v).strip()
    return v or "-"


def build_cloud_api_payload(message: OutgoingMessage) -> dict[str, Any]:
    """Corpo JSON de POST /{phone-number-id}/messages (Cloud API)."""
    base: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": digits_only(message.to),
    }

    if message.template is not None:
        components: list[dict[str, Any]] = []
        if message.media is not None:
            kind = _MEDIA_KIND[message.media.type]
            media: dict[str, str] = {"link": message.media.url}
            if kind == "document" and message.media.filename:
                media["filename"] = message.media.filename
            components.append({"type": "header", "parameters": [{"type": kind, kind: media}]})
        if message.template.parameters:
            components.append(
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": sanitize_template_param(p)} for p in message.template.parameters],
                }
            )
        template: dict[str, Any] = {"name": message.template.name, "language": {"code": message.template.language}}
        if components:
            template["components"] = components
        return {**base, "type": "template", "template": template}

    if message.media is not None:
        kind = _MEDIA_KIND[message.media.type]
        media = {"link": message.media.url}
        if (message.text or "").strip():
            media["caption"] = message.text
        if kind == "document" and message.media.filename:
            media["filename"] = message.media.filename
        return {**base, "type": kind, kind: media}

    return {**base, "type": "text", "text": {"body": message.text, "preview_url": True}}


def parse_cloud_api_send_response(status: int, data: Any) -> SendResult:
    """Interpreta a resposta do envio (Cloud API / 360dialog)."""
    body = data if isinstance(data, dict) else {}
    messages = body.get("messages")
    message_id = messages[0].get("id") if isinstance(messages, list) and messages and isinstance(messages[0], dict) else None
    if 200 <= status < 300 and message_id:
        return SendResult(ok=True, provider_message_id=str(message_id))

    errors = body.get("errors")
    err_obj = body.get("error") if isinstance(body.get("error"), dict) else None
    if err_obj is None and isinstance(errors, list) and errors and isinstance(errors[0], dict):
        err_obj = errors[0]
    code = _as_int(err_obj.get("code")) if err_obj else None
    meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
    error = describe_cloud_error(err_obj)
    if not error and meta.get("developer_message"):
        error = truncate(str(meta["developer_message"]), 300)
    if not error:
        error = "Resposta do provedor sem id da mensagem" if 200 <= status < 300 else f"Erro HTTP {status} do provedor"
    retryable = status == 429 or status >= 500 or (code is not None and code in RETRYABLE_CLOUD_ERROR_CODES)
    return SendResult(ok=False, error=error, retryable=retryable)


def quality_label(rating: str | None) -> str | None:
    if not rating:
        return None
    return QUALITY_LABELS.get(rating.upper(), rating.lower())


# ------------------------------------------------------------------------------------------------ Webhooks

_STATUS_MAP = {"sent": "SENT", "delivered": "DELIVERED", "read": "READ", "failed": "FAILED"}
_MEDIA_LABELS = {
    "image": "[imagem]",
    "audio": "[áudio]",
    "voice": "[áudio]",
    "video": "[vídeo]",
    "document": "[documento]",
    "sticker": "[figurinha]",
    "location": "[localização]",
    "contacts": "[contato]",
    "reaction": "[reação]",
    "unsupported": "[mensagem não suportada]",
}


def _get(obj: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _inbound_body(message: dict) -> str:
    body = (
        _get(message, "text", "body")
        or _get(message, "button", "text")
        or _get(message, "interactive", "button_reply", "title")
        or _get(message, "interactive", "list_reply", "title")
        or _get(message, "image", "caption")
        or _get(message, "video", "caption")
        or _get(message, "document", "caption")
        or _get(message, "reaction", "emoji")
    )
    if body:
        return str(body)
    kind = message.get("type")
    return _MEDIA_LABELS.get(kind, f"[{kind}]" if kind else "")


def _events_from_value(value: dict, out: list[WebhookEvent]) -> None:
    for s in value.get("statuses") if isinstance(value.get("statuses"), list) else []:
        if not isinstance(s, dict):
            continue
        status = _STATUS_MAP.get(str(s.get("status") or "").lower())
        if not s.get("id") or not status:
            continue
        error = ""
        if status == "FAILED":
            errors = s.get("errors")
            error = describe_cloud_error(errors[0] if isinstance(errors, list) and errors else None) or (
                "Falha na entrega informada pela Meta"
            )
        out.append(
            WebhookEvent(
                kind="status",
                provider_message_id=str(s["id"]),
                status=status,
                error=error,
                timestamp=unix_to_datetime(s.get("timestamp")),
            )
        )
    for m in value.get("messages") if isinstance(value.get("messages"), list) else []:
        if not isinstance(m, dict):
            continue
        sender = digits_only(str(m.get("from") or ""))
        if not sender:
            continue
        out.append(
            WebhookEvent(
                kind="inbound",
                from_phone=sender,
                body=_inbound_body(m),
                timestamp=unix_to_datetime(m.get("timestamp")),
            )
        )


def parse_cloud_api_webhook_body(raw_body: bytes | str) -> list[WebhookEvent]:
    """Converte o corpo de um webhook da Cloud API em eventos normalizados.

    Formato: {object, entry:[{changes:[{value:{statuses:[...], messages:[...]}}]}]}. Também aceita o formato
    "achatado" (statuses/messages na raiz) usado pela 360dialog v1.
    """
    try:
        payload = json.loads(raw_body)
    except (ValueError, TypeError):
        return []
    if not isinstance(payload, dict):
        return []
    out: list[WebhookEvent] = []
    entries = payload.get("entry")
    for entry in entries if isinstance(entries, list) else []:
        changes = entry.get("changes") if isinstance(entry, dict) else None
        for change in changes if isinstance(changes, list) else []:
            value = change.get("value") if isinstance(change, dict) else None
            if isinstance(value, dict):
                _events_from_value(value, out)
    if not isinstance(entries, list) and ("statuses" in payload or "messages" in payload):
        _events_from_value(payload, out)
    return out


_CHALLENGE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,512}$")
_TEXT_PLAIN = "text/plain; charset=utf-8"


def handle_cloud_verification(req: WebhookRequest, webhook_token: str) -> WebhookResponse | None:
    """Handshake de verificação da Meta: GET ?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...

    Retorna None se a requisição não for de verificação; 403 se o token não confere.
    """
    if req.method.upper() != "GET":
        return None
    mode = req.query.get("hub.mode")
    if not mode:
        return None
    token = req.query.get("hub.verify_token") or ""
    challenge = req.query.get("hub.challenge") or ""
    if mode != "subscribe" or not webhook_token or not safe_equal(token, webhook_token):
        return WebhookResponse(status=403, body="Forbidden", content_type=_TEXT_PLAIN)
    if not _CHALLENGE_RE.match(challenge):
        return WebhookResponse(status=400, body="Bad request", content_type=_TEXT_PLAIN)
    return WebhookResponse(status=200, body=challenge, content_type=_TEXT_PLAIN)


def compute_cloud_signature(app_secret: str, raw_body: bytes) -> str:
    return "sha256=" + hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def verify_cloud_signature(raw_body: bytes, header: str | None, app_secret: str | None) -> bool:
    """Valida X-Hub-Signature-256. Sem App Secret configurado, aceita (a URL secreta já autentica)."""
    if not app_secret:
        return True
    if not header or not header.lower().startswith("sha256="):
        return False
    received = "sha256=" + header[7:].strip().lower()
    return safe_equal(received, compute_cloud_signature(app_secret, raw_body))
