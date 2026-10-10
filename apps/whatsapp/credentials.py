"""Validação, normalização e mascaramento das credenciais dos provedores (funções puras).
Segredos nunca voltam ao navegador: a interface recebe apenas a versão mascarada (`mask_secret`)."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping

from apps.core.crypto import mask_secret

from .providers.cloud_api import DEFAULT_GRAPH_API_VERSION
from .providers.dialog360 import is_allowed_dialog360_url
from .providers.sandbox import SANDBOX_MAX_FAILURE_RATE
from .types import ProviderField

MAX_CREDENTIAL_LENGTH = 4096

# Valores sugeridos ao criar uma conexão
DEFAULT_CREDENTIALS = {"api_version": DEFAULT_GRAPH_API_VERSION, "failure_rate": "0.05"}


class CredentialError(ValueError):
    """Valor de credencial inválido (a mensagem é exibida ao usuário, em pt-BR)."""


Rule = Callable[[str], str]


def _no_spaces(label: str, min_length: int) -> Rule:
    def rule(value: str) -> str:
        if re.search(r"\s", value):
            raise CredentialError(f"{label} não pode conter espaços.")
        if len(value) < min_length:
            raise CredentialError(f"{label} parece incompleto.")
        return value

    return rule


def _numeric_id(value: str) -> str:
    if not re.fullmatch(r"\d{5,25}", value):
        raise CredentialError("Informe apenas os números do ID.")
    return value


def _api_version(value: str) -> str:
    normalized = value.lower() if value.lower().startswith("v") else f"v{value.lower()}"
    if not re.fullmatch(r"v\d{1,2}\.\d", normalized):
        raise CredentialError("Use o formato v21.0.")
    return normalized


def _dialog360_url(value: str) -> str:
    if not is_allowed_dialog360_url(value):
        raise CredentialError("Use um endereço https da 360dialog, ex.: https://waba-v2.360dialog.io.")
    return value.rstrip("/")


def _twilio_from(value: str) -> str:
    digits = re.sub(r"[\s().-]", "", re.sub(r"^whatsapp:", "", value, flags=re.IGNORECASE))
    if not re.fullmatch(r"\+?\d{10,15}", digits):
        raise CredentialError("Use o formato internacional, ex.: +5511999999999.")
    return "+" + digits.lstrip("+")


def _failure_rate(value: str) -> str:
    try:
        n = float(value.replace(",", "."))
    except ValueError:
        n = -1.0
    if not 0 <= n <= SANDBOX_MAX_FAILURE_RATE:
        raise CredentialError("Informe um valor entre 0 e 0,5.")
    return format(n, "g")


def _pattern(regex: str, message: str) -> Rule:
    def rule(value: str) -> str:
        if not re.fullmatch(regex, value):
            raise CredentialError(message)
        return value

    return rule


# Regras específicas por provedor e campo (valor já aparado e não vazio)
FIELD_RULES: dict[str, dict[str, Rule]] = {
    "META_CLOUD": {
        "phone_number_id": _numeric_id,
        "business_account_id": _numeric_id,
        "access_token": _no_spaces("O token", 20),
        "app_secret": _no_spaces("A chave secreta", 16),
        "api_version": _api_version,
    },
    "DIALOG360": {
        "api_key": _no_spaces("A chave de API", 10),
        "base_url": _dialog360_url,
    },
    "TWILIO": {
        "account_sid": _pattern(r"AC[0-9a-fA-F]{32}", "O Account SID começa com AC e tem 34 caracteres."),
        "auth_token": _no_spaces("O Auth Token", 16),
        "from_number": _twilio_from,
        "messaging_service_sid": _pattern(r"MG[0-9a-fA-F]{32}", "O Messaging Service SID começa com MG e tem 34 caracteres."),
    },
    "SANDBOX": {"failure_rate": _failure_rate},
}


def validate_credential(provider_key: str, field: ProviderField, value: str) -> str:
    """Valida/normaliza um valor não vazio digitado para o campo; lança CredentialError."""
    if len(value) > MAX_CREDENTIAL_LENGTH:
        raise CredentialError("Valor muito longo.")
    rule = FIELD_RULES.get(provider_key, {}).get(field.name)
    return rule(value) if rule else value


def split_credentials(fields: list[ProviderField], credentials: Mapping[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Separa as credenciais em valores visíveis (campos comuns) e segredos mascarados."""
    values: dict[str, str] = {}
    masked: dict[str, str] = {}
    for spec in fields:
        value = credentials.get(spec.name)
        if not value:
            continue
        if spec.secret:
            masked[spec.name] = mask_secret(value)
        else:
            values[spec.name] = value
    return values, masked
