"""Links de cadastro e QR Codes (segno, sem dependências nativas)."""

from __future__ import annotations

import io

import segno
from django.conf import settings


def app_url(path: str = "/") -> str:
    """URL pública absoluta (APP_URL + caminho)."""
    return f"{settings.APP_URL}{path if path.startswith('/') else '/' + path}"


def registration_url(invite_code: str, source: str = "link") -> str:
    """URL pública do formulário de cadastro de um usuário. QR Codes usam ?src=qr para medir a origem."""
    return app_url(f"/c/{invite_code}/" + ("?src=qr" if source == "qr" else ""))


def qr_png_data_url(text: str, scale: int = 10, dark: str = "#0f172a") -> str:
    """QR Code como data URL PNG."""
    qr = segno.make(text, error="m")
    return qr.png_data_uri(scale=scale, border=2, dark=dark, light="#ffffff")


def qr_svg(text: str, scale: int = 10, dark: str = "#0f172a") -> str:
    """QR Code como SVG inline (nítido para impressão)."""
    qr = segno.make(text, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=scale, border=2, dark=dark, light="#ffffff", xmldecl=False, svgns=True)
    return buf.getvalue().decode("utf-8")
