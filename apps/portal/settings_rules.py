"""Regras puras das configurações da campanha (sem banco, sem request): cor, logo, grupos do formulário e diff.

O servidor NUNCA confia no navegador: a cor e o logo enviados são revalidados aqui mesmo depois do
redimensionamento feito em JavaScript (`static/js/portal/settings.js`).
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Mapping
from typing import Any

from apps.core.constants import FORM_FIELD_MODES

# --- Limites de texto (compartilhados entre os campos do HTML e a validação do servidor) ------------
LIMITS = {
    "candidate_name": 120,
    "ballot_name": 60,
    "party": 40,
    "city": 80,
    "form_title": 120,
    "form_message": 600,
    "consent_text_min": 40,
    "consent_text_max": 3000,
    "privacy_contact": 160,
    "voter_goal_max": 10_000_000,
    "election_year_min": 2000,
    "election_year_max": 2100,
}

# --- Cor principal ------------------------------------------------------------------------------------
HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}")
DEFAULT_PRIMARY_COLOR = "#4f46e5"


def is_hex_color(value: Any) -> bool:
    return isinstance(value, str) and HEX_COLOR_RE.fullmatch(value) is not None


def normalize_hex_color(value: Any) -> str | None:
    """"#ABCDEF" → "#abcdef"; None quando não for exatamente #RRGGBB."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value.lower() if HEX_COLOR_RE.fullmatch(value) else None


def _relative_luminance(hex_color: str) -> float:
    color = normalize_hex_color(hex_color) or DEFAULT_PRIMARY_COLOR

    def channel(start: int) -> float:
        c = int(color[start : start + 2], 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5)


def readable_text_color(hex_color: str) -> str:
    """Cor de texto (#ffffff ou #0f172a) com melhor contraste sobre o fundo informado (WCAG)."""
    lum = _relative_luminance(hex_color)
    with_white = 1.05 / (lum + 0.05)
    with_dark = (lum + 0.05) / (_relative_luminance("#0f172a") + 0.05)
    return "#ffffff" if with_white >= with_dark else "#0f172a"


# --- Logo (data URL) ----------------------------------------------------------------------------------
LOGO_MAX_BYTES = 300 * 1024  # tamanho máximo decodificado
LOGO_MAX_DIMENSION = 512  # lado máximo gerado pelo navegador
LOGO_MAX_SOURCE_BYTES = 15 * 1024 * 1024  # arquivo original escolhido (antes de reduzir no navegador)
LOGO_MAX_SERVER_DIMENSION = 4096  # tolerância do servidor (evita "bombas" de descompressão)
LOGO_ACCEPTED_MIMES = ("image/png", "image/jpeg", "image/webp")
# Teto de caracteres do campo (base64 cresce 4/3 + prefixo); descarta payloads absurdos antes de decodificar
LOGO_DATA_URL_MAX_CHARS = LOGO_MAX_BYTES * 4 // 3 + 64

_LOGO_RE = re.compile(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})")


def is_safe_logo_url(value: Any) -> bool:
    """True quando o logo salvo é um data URL de imagem permitido (seguro para usar em <img src>)."""
    return isinstance(value, str) and len(value) <= LOGO_DATA_URL_MAX_CHARS * 2 and _LOGO_RE.fullmatch(value) is not None


class LogoError(ValueError):
    """Logo inválido (a mensagem já está em pt-BR e pode ser exibida ao usuário)."""


def _png_size(raw: bytes) -> tuple[int, int] | None:
    if len(raw) >= 24 and raw[12:16] == b"IHDR":
        return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")
    return None


def _webp_size(raw: bytes) -> tuple[int, int] | None:
    chunk = raw[12:16]
    if chunk == b"VP8X" and len(raw) >= 30:
        return int.from_bytes(raw[24:27], "little") + 1, int.from_bytes(raw[27:30], "little") + 1
    if chunk == b"VP8L" and len(raw) >= 25 and raw[20] == 0x2F:
        bits = int.from_bytes(raw[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8 " and len(raw) >= 30 and raw[23:26] == b"\x9d\x01\x2a":
        return int.from_bytes(raw[26:28], "little") & 0x3FFF, int.from_bytes(raw[28:30], "little") & 0x3FFF
    return None


def _jpeg_size(raw: bytes) -> tuple[int, int] | None:
    i, n = 2, len(raw)
    while i + 9 < n:
        if raw[i] != 0xFF:
            i += 1
            continue
        marker = raw[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
            i += 1 if marker == 0xFF else 2
            continue
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):  # SOFn
            return int.from_bytes(raw[i + 7 : i + 9], "big"), int.from_bytes(raw[i + 5 : i + 7], "big")
        i += 2 + int.from_bytes(raw[i + 2 : i + 4], "big")
    return None


def _signature_ok(subtype: str, raw: bytes) -> bool:
    if subtype == "png":
        return raw.startswith(b"\x89PNG\r\n\x1a\n")
    if subtype == "jpeg":
        return raw.startswith(b"\xff\xd8\xff")
    return len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"


def image_dimensions(subtype: str, raw: bytes) -> tuple[int, int] | None:
    """Largura e altura lidas do cabeçalho do arquivo (None quando não for possível determinar)."""
    return {"png": _png_size, "webp": _webp_size, "jpeg": _jpeg_size}[subtype](raw)


def check_logo_data_url(value: str, max_bytes: int = LOGO_MAX_BYTES) -> tuple[str, int]:
    """Valida um logo enviado como data URL e devolve (mime, bytes decodificados).

    Exige o prefixo `data:image/(png|jpeg|webp);base64,`, base64 estrito, tamanho decodificado ≤ `max_bytes`,
    assinatura binária compatível com o tipo declarado e dimensões razoáveis. Levanta `LogoError`.
    """
    match = _LOGO_RE.fullmatch(value or "")
    if match is None:
        raise LogoError("Envie uma imagem PNG, JPEG ou WebP.")
    subtype, payload = match.group(1), match.group(2)
    if len(payload) > max_bytes * 4 // 3 + 4:  # evita decodificar algo claramente grande demais
        raise LogoError(f"A imagem deve ter no máximo {max_bytes // 1024} KB.")
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise LogoError("Imagem corrompida. Tente enviar novamente.") from None
    if not raw:
        raise LogoError("Imagem vazia.")
    if len(raw) > max_bytes:
        raise LogoError(f"A imagem deve ter no máximo {max_bytes // 1024} KB.")
    if not _signature_ok(subtype, raw):
        raise LogoError("O conteúdo do arquivo não corresponde a uma imagem válida.")
    size = image_dimensions(subtype, raw)
    if size is not None and (min(size) < 1 or max(size) > LOGO_MAX_SERVER_DIMENSION):
        raise LogoError("As dimensões da imagem são inválidas ou grandes demais.")
    return f"image/{subtype}", len(raw)


# --- Formulário público -------------------------------------------------------------------------------
FORM_FIELD_MODE_LABELS = {"hidden": "Oculto", "optional": "Opcional", "required": "Obrigatório"}
FORM_FIELD_MODE_CHOICES = [(mode, FORM_FIELD_MODE_LABELS[mode]) for mode in FORM_FIELD_MODES]

# Chaves = chaves de Campaign.form_config (apps.core.constants.DEFAULT_FORM_CONFIG)
FORM_FIELD_GROUPS = [
    {"key": "email", "label": "E-mail", "description": "Endereço de e-mail do apoiador."},
    {"key": "birth_date", "label": "Data de nascimento", "description": "Permite filtrar por faixa etária."},
    {"key": "gender", "label": "Gênero", "description": "Masculino, feminino, outro ou prefere não informar."},
    {
        "key": "address",
        "label": "Endereço",
        "description": "CEP, rua, número, bairro e cidade. Alimenta o mapa por bairro.",
    },
    {"key": "electoral", "label": "Zona e seção eleitoral", "description": "Dados do título de apoiador."},
]


# --- Diferença entre versões (auditoria: somente NOMES de campos) -------------------------------------
def _normalize(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, Mapping):
        return {str(k): _normalize(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    return value


def same_value(a: Any, b: Any) -> bool:
    """Igualdade estrutural: None, "" e ausência são equivalentes; a ordem das chaves não importa."""
    return _normalize(a) == _normalize(b)


def changed_fields(previous: Mapping[str, Any], new: Mapping[str, Any]) -> list[str]:
    """Nomes dos campos de `new` cujo valor difere de `previous` (nunca os valores)."""
    return [key for key, value in new.items() if not same_value(previous.get(key), value)]
