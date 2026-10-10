"""Utilitários HTTP e de texto compartilhados pelos provedores de WhatsApp.

Sem dependência de request/messages/decorators (o worker importa estes módulos).
Nunca registre tokens, telefones ou corpos de mensagem em log.
"""

from __future__ import annotations

import hmac
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from ..types import SendResult

PROVIDER_TIMEOUT_SECONDS = 15.0


class ProviderNetworkError(Exception):
    """Falha de rede/timeout ao falar com o provedor (sempre vale tentar de novo)."""

    def __init__(self, message: str, timeout: bool = False):
        super().__init__(message)
        self.message = message
        self.timeout = timeout


@dataclass
class HttpResult:
    status: int
    ok: bool
    data: Any = None  # corpo interpretado como JSON (None se vazio ou inválido)


def provider_request(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    json_body: Any = None,
    form: Mapping[str, str] | None = None,
    auth: tuple[str, str] | None = None,
) -> HttpResult:
    """Requisição HTTP com timeout de 15 s e leitura tolerante do corpo JSON. Não segue redirecionamentos."""
    try:
        response = httpx.request(
            method,
            url,
            headers=dict(headers or {}),
            json=json_body,
            data=dict(form) if form is not None else None,
            auth=auth,
            timeout=PROVIDER_TIMEOUT_SECONDS,
            follow_redirects=False,
        )
    except httpx.TimeoutException as exc:
        raise ProviderNetworkError("Tempo esgotado ao contatar o provedor", timeout=True) from exc
    except httpx.HTTPError as exc:
        raise ProviderNetworkError("Falha de rede ao contatar o provedor") from exc
    data: Any = None
    if response.content:
        try:
            data = response.json()
        except ValueError:
            data = None
    return HttpResult(status=response.status_code, ok=response.is_success, data=data)


def send_failure_from_error(exc: Exception) -> SendResult:
    """Converte exceções de envio em SendResult (rede/timeout = retryable)."""
    if isinstance(exc, ProviderNetworkError):
        return SendResult(ok=False, error=exc.message, retryable=True)
    return SendResult(ok=False, error="Erro inesperado ao enviar a mensagem", retryable=True)


def check_failure_message(exc: Exception) -> str:
    """Mensagem para falhas inesperadas ao testar a conexão."""
    if isinstance(exc, ProviderNetworkError):
        return exc.message
    return "Erro inesperado ao testar a conexão"


def digits_only(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def is_valid_recipient(value: str | None) -> bool:
    """Telefone de destino aceitável pelos provedores: só dígitos, com DDI, 10 a 15 dígitos."""
    return 10 <= len(digits_only(value)) <= 15


def truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def unix_to_datetime(value: Any) -> datetime | None:
    """Timestamp Unix (segundos, string ou número) → datetime UTC."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    try:
        return datetime.fromtimestamp(n, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def safe_equal(a: str, b: str) -> bool:
    """Comparação de strings em tempo constante."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])([A-Z])")


def snake_key(key: str) -> str:
    """"failureRate" → "failure_rate"; chaves já em snake_case e "__connection_id" ficam como estão."""
    return _CAMEL_BOUNDARY.sub(lambda m: "_" + m.group(1).lower(), key)


def normalize_credentials(credentials: Mapping[str, Any] | None) -> dict[str, str]:
    """Credenciais com chaves em snake_case e valores string (aceita camelCase do seed/legado)."""
    out: dict[str, str] = {}
    for key, value in (credentials or {}).items():
        if not isinstance(key, str) or isinstance(value, (dict, list, tuple, set)):
            continue
        out[snake_key(key)] = "" if value is None else str(value)
    return out
