"""Utilitários puros do módulo de apoiadores (sem banco): datas, textos, cores da campanha, WhatsApp, ordenação.

Portado das regras da versão anterior (legacy-nextjs/src/components/voters/voter-utils.ts).
"""

from __future__ import annotations

import ipaddress
import re
from datetime import date
from urllib.parse import quote

from django.db.models.functions import Lower

from apps.core.utils import title_case

# ---------------------------------------------------------------------------------------------
# Código do link de cadastro
# ---------------------------------------------------------------------------------------------

INVITE_CODE_RE = re.compile(r"^[A-Za-z0-9]{4,32}$")


def is_valid_invite_code(code: str | None) -> bool:
    return bool(code) and INVITE_CODE_RE.match(code) is not None


# ---------------------------------------------------------------------------------------------
# Datas
# ---------------------------------------------------------------------------------------------

MIN_VOTER_AGE = 16
MAX_VOTER_AGE = 120

# Formatos aceitos para a data de nascimento digitada (campo de texto com máscara dd/mm/aaaa)
_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ].*)?$")
_BR_DATE = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$")
_COMPACT_DATE = re.compile(r"^(\d{2})(\d{2})(\d{4})$")


def parse_birth_date_input(value: str | None) -> date | None:
    """"dd/mm/aaaa", "dd-mm-aaaa", "dd.mm.aaaa", "ddmmaaaa" ou "aaaa-mm-dd" → date (None se inválida)."""
    s = (value or "").strip()
    if not s:
        return None
    if m := _ISO_DATE.match(s):
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
    elif m := _BR_DATE.match(s):
        d, mo, y = int(m[1]), int(m[2]), int(m[3])
    elif m := _COMPACT_DATE.match(s):
        d, mo, y = int(m[1]), int(m[2]), int(m[3])
    else:
        return None
    if y < 1800:
        return None
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def is_voter_age(age: int | None) -> bool:
    return age is not None and MIN_VOTER_AGE <= age <= MAX_VOTER_AGE


def format_birth_date(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else ""


# ---------------------------------------------------------------------------------------------
# Textos
# ---------------------------------------------------------------------------------------------

_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


def has_letter(value: str) -> bool:
    return _HAS_LETTER.search(value or "") is not None


def collapse_spaces(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def smart_case(value: str | None) -> str:
    """Normaliza espaços; se estiver todo em minúsculas ou MAIÚSCULAS aplica title_case (rua, bairro, cidade)."""
    v = collapse_spaces(value)
    if not v:
        return v
    if v == v.lower() or v == v.upper():
        return title_case(v)
    return v


def only_digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def normalize_digits_field(value: str | None, max_digits: int) -> str | None:
    """Zona (até 4 dígitos) e seção (até 5): sem zeros à esquerda. None se inválido."""
    v = (value or "").strip()
    if not re.fullmatch(rf"\d{{1,{max_digits}}}", v):
        return None
    return str(int(v))


def whatsapp_share_url(text: str) -> str:
    """Link de compartilhamento no WhatsApp (sem destinatário)."""
    return f"https://wa.me/?text={quote(text, safe='')}"


def short_url(url: str) -> str:
    """"https://efind.com.br/c/abc/" → "efind.com.br/c/abc" """
    return re.sub(r"/+$", "", re.sub(r"^https?://", "", url or "", flags=re.IGNORECASE))


def safe_ip(value: str | None) -> str | None:
    """IP válido (v4/v6) ou None — nunca grava lixo em GenericIPAddressField."""
    try:
        return str(ipaddress.ip_address((value or "").strip()))
    except ValueError:
        return None


_SVG_SIZE = re.compile(r'\swidth="(\d+(?:\.\d+)?)"\s+height="(\d+(?:\.\d+)?)"')


def scalable_svg(svg: str) -> str:
    """Troca width/height fixos do SVG do QR Code por viewBox, para escalar com CSS (impressão nítida)."""
    return _SVG_SIZE.sub(lambda m: f' viewBox="0 0 {m[1]} {m[2]}" preserveAspectRatio="xMidYMid meet"', svg, count=1)


# ---------------------------------------------------------------------------------------------
# Logo e cores da campanha (páginas públicas)
# ---------------------------------------------------------------------------------------------

DEFAULT_BRAND_COLOR = "#4f46e5"
_HEX_RE = re.compile(r"^#(?:[0-9a-f]{3}|[0-9a-f]{6})$", re.IGNORECASE)
_DATA_IMAGE_RE = re.compile(r"^data:image/(?:png|jpe?g|webp|gif);base64,[A-Za-z0-9+/=]+$")


def safe_logo_url(url: str | None) -> str:
    """Aceita apenas data URL de imagem raster, http(s) ou caminho local (evita javascript:/svg no src)."""
    u = (url or "").strip()
    if not u:
        return ""
    if _DATA_IMAGE_RE.match(u):
        return u
    if re.match(r"^https?://[^\s\"'<>]+$", u, flags=re.IGNORECASE):
        return u
    if u.startswith("/") and not u.startswith("//") and not re.search(r"[\s\"'<>]", u):
        return u
    return ""


def is_hex_color(value: str | None) -> bool:
    return bool(value) and _HEX_RE.match(value.strip()) is not None


def safe_hex_color(value: str | None, fallback: str = DEFAULT_BRAND_COLOR) -> str:
    """Cor validada em "#rrggbb" minúsculo (cai no padrão se inválida)."""
    if not is_hex_color(value):
        return fallback
    h = value.strip().lower()[1:]
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return f"#{h}"


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    h = safe_hex_color(color)[1:]
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(min(255, max(0, c))):02x}" for c in rgb)


def mix_hex(color: str, other: str, weight: float) -> str:
    """Mistura `color` com `other` (weight = proporção de `other`, 0–1)."""
    a, b = _hex_to_rgb(color), _hex_to_rgb(other)
    return _rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * weight for i in range(3)))


def _luminance(color: str) -> float:
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in _hex_to_rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def readable_text_color(background: str) -> str:
    """Cor de texto legível sobre o fundo: branco ou grafite."""
    bg = safe_hex_color(background)
    return "#ffffff" if _contrast(bg, "#ffffff") >= _contrast(bg, "#0f172a") else "#0f172a"


def brand_css_vars(color: str) -> dict[str, str]:
    """Variáveis CSS que recolorem as classes brand-* do Tailwind com a cor da campanha."""
    c = safe_hex_color(color)
    return {
        "--color-brand-50": mix_hex(c, "#ffffff", 0.92),
        "--color-brand-100": mix_hex(c, "#ffffff", 0.84),
        "--color-brand-200": mix_hex(c, "#ffffff", 0.68),
        "--color-brand-300": mix_hex(c, "#ffffff", 0.48),
        "--color-brand-400": mix_hex(c, "#ffffff", 0.24),
        "--color-brand-500": mix_hex(c, "#ffffff", 0.08),
        "--color-brand-600": c,
        "--color-brand-700": mix_hex(c, "#000000", 0.15),
        "--color-brand-800": mix_hex(c, "#000000", 0.3),
    }


def brand_style(color: str) -> str:
    """Valor do atributo style com as variáveis de marca (somente hexadecimais validados)."""
    return ";".join(f"{k}:{v}" for k, v in brand_css_vars(color).items())


# ---------------------------------------------------------------------------------------------
# Situação do WhatsApp
# ---------------------------------------------------------------------------------------------

WA_APTO = "APTO"
WA_OPTED_OUT = "DESCADASTRADO"
WA_NO_CONSENT = "SEM_AUTORIZACAO"
WHATSAPP_STATUS_LABELS = {
    WA_APTO: "Apto a WhatsApp",
    WA_OPTED_OUT: "Descadastrado",
    WA_NO_CONSENT: "Sem autorização",
}
WHATSAPP_STATUS_TONES = {WA_APTO: "green", WA_OPTED_OUT: "red", WA_NO_CONSENT: "gray"}


def whatsapp_status_of(voter) -> str:
    """Mesma regra de MESSAGEABLE_Q: opt-in + consentimento + sem descadastro."""
    if voter.opt_out_at:
        return WA_OPTED_OUT
    if voter.whatsapp_opt_in and voter.consent_at:
        return WA_APTO
    return WA_NO_CONSENT


# ---------------------------------------------------------------------------------------------
# Ordenação da lista
# ---------------------------------------------------------------------------------------------

VOTER_SORTS = {
    "recentes": "Mais recentes",
    "antigos": "Mais antigos",
    "nome": "Nome (A–Z)",
}
DEFAULT_SORT = "recentes"


def parse_voter_sort(value: str | None) -> str:
    return value if value in VOTER_SORTS else DEFAULT_SORT


def sort_expressions(sort: str) -> tuple:
    """Expressões de order_by (sempre com desempate por pk para paginação estável)."""
    if sort == "antigos":
        return ("created_at", "pk")
    if sort == "nome":
        return (Lower("name"), "pk")
    return ("-created_at", "pk")

