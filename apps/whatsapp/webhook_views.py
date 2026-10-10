"""Endpoint público dos webhooks dos provedores (/api/webhooks/whatsapp/<token>/).

Sem login e sem CSRF (quem chama é o provedor): a conexão é localizada pelo `webhook_token` (aleatório, na URL) e,
quando o provedor assina o corpo (Meta, Twilio), a assinatura é validada em tempo constante antes de qualquer
processamento. Nunca registra corpo, telefones ou tokens em log.
"""

from __future__ import annotations

import logging

from django.core.exceptions import RequestDataTooBig
from django.http import HttpRequest, HttpResponse
from django.http.request import RawPostDataException
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.core.constants import ConnectionStatus

from .models import WhatsAppConnection
from .registry import decrypt_credentials, get_provider_definition, webhook_url_for
from .types import WebhookRequest
from .webhook import apply_webhook_events

logger = logging.getLogger(__name__)

MAX_WEBHOOK_BODY_BYTES = 1_000_000
TEXT_PLAIN = "text/plain; charset=utf-8"


def _text(body: str, status: int = 200) -> HttpResponse:
    return HttpResponse(body, status=status, content_type=TEXT_PLAIN)


def _public_url(token: str, request: HttpRequest) -> str:
    """URL pública da chamada (a Twilio assina exatamente a URL configurada, com a querystring, se houver)."""
    url = webhook_url_for(token)
    query = request.META.get("QUERY_STRING", "")
    return f"{url}?{query}" if query else url


def _build_request(request: HttpRequest, token: str, raw_body: bytes) -> WebhookRequest:
    return WebhookRequest(
        method=request.method or "",
        url=_public_url(token, request),
        headers={key.lower(): value for key, value in request.headers.items()},
        raw_body=raw_body,
        query={key: request.GET.get(key, "") for key in request.GET},
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
def webhook(request: HttpRequest, token: str) -> HttpResponse:
    # Só conexões ativas; token desconhecido ou desativado = 404 (sem revelar mais nada)
    connection = (
        WhatsAppConnection.objects.filter(webhook_token=token[:64]).exclude(status=ConnectionStatus.DISABLED).first()
        if token
        else None
    )
    definition = get_provider_definition(connection.provider) if connection else None
    if connection is None or definition is None:
        return _text("Not found", 404)

    try:
        credentials = decrypt_credentials(connection.credentials)
    except Exception as exc:  # noqa: BLE001 - chave de criptografia trocada ou dado corrompido
        logger.error("Credenciais ilegíveis no webhook do WhatsApp (%s): %s", connection.provider, type(exc).__name__)
        credentials = None

    # ------------------------------------------------------------------ GET: verificação (handshake da Meta)
    if request.method == "GET":
        req = _build_request(request, token, b"")
        if definition.handle_verification is not None:
            response = definition.handle_verification(req, credentials or {}, connection.webhook_token)
            if response is not None:
                return HttpResponse(response.body, status=response.status, content_type=response.content_type)
        return _text("ok")

    # ------------------------------------------------------------------ POST: eventos
    try:
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        declared = 0
    if declared > MAX_WEBHOOK_BODY_BYTES:
        return _text("Payload too large", 413)
    try:
        raw_body = request.body
    except (RequestDataTooBig, RawPostDataException):
        return _text("Payload too large", 413)
    if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
        return _text("Payload too large", 413)

    req = _build_request(request, token, raw_body)
    if definition.verify_signature is not None:
        if credentials is None:  # não há como validar a assinatura: melhor pedir nova tentativa do que aceitar sem validar
            return _text("Service unavailable", 503)
        if not definition.verify_signature(req, credentials):
            return _text("Invalid signature", 401)

    try:
        events = definition.parse_webhook(req)
        if events:
            apply_webhook_events(connection, events)
    except Exception as exc:  # noqa: BLE001 - o provedor não deve reenviar em loop por erro nosso
        logger.error("Falha ao processar webhook do WhatsApp (%s): %s", connection.provider, type(exc).__name__)
    return _text("ok")
