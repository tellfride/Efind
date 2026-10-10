"""Utilitários gerais (texto, tags, datas, CSV, IP, QR Code)."""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections.abc import Iterable
from datetime import date, datetime

from django.conf import settings


def normalize_text(value: str) -> str:
    """Remove acentos e baixa a caixa — útil para comparar bairros/tags."""
    nfd = unicodedata.normalize("NFD", value or "")
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").lower().strip()


def slugify(value: str, max_length: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", normalize_text(value)).strip("-")
    return s[:max_length].strip("-")


_LOWER_WORDS = {"da", "de", "do", "das", "dos", "e"}


def title_case(value: str) -> str:
    """"MARIA DA SILVA" → "Maria da Silva" """
    words = re.sub(r"\s+", " ", (value or "").strip()).lower().split(" ")
    out = []
    for i, w in enumerate(words):
        out.append(w if (i > 0 and w in _LOWER_WORDS) or not w else w[0].upper() + w[1:])
    return " ".join(out)


def first_name(full_name: str | None) -> str:
    parts = (full_name or "").strip().split()
    return parts[0] if parts else ""


def initials(name: str | None) -> str:
    parts = (name or "").strip().split()
    if not parts:
        return "?"
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()


def serialize_tags(value: str | Iterable[str] | None) -> str | None:
    """Tags: entrada livre "Saúde, Jovem" → string armazenada ",saude,jovem,"."""
    items = value.split(",") if isinstance(value, str) else list(value or [])
    seen: list[str] = []
    for t in items:
        s = slugify(t)
        if s and s not in seen:
            seen.append(s)
    return f",{','.join(seen)}," if seen else None


def parse_tags(stored: str | None) -> list[str]:
    return [t for t in (stored or "").split(",") if t]


def age_from(birth: date | datetime | None, today: date | None = None) -> int | None:
    """Idade em anos completos."""
    if not birth:
        return None
    if isinstance(birth, datetime):
        birth = birth.date()
    today = today or date.today()
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def client_ip(request) -> str:
    """IP do cliente (considera proxy reverso em X-Forwarded-For apenas quando configurado)."""
    fwd = request.META.get("HTTP_X_FORWARDED_FOR")
    if fwd and getattr(settings, "SECURE_PROXY_SSL_HEADER", None):
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or "0.0.0.0"


def _csv_cell(value) -> str:
    if value is None:
        return ""
    s = value.isoformat() if isinstance(value, (date, datetime)) else str(value)
    # Evita injeção de fórmulas no Excel
    if s and s[0] in "=+-@\t\r":
        s = "'" + s
    return s


def to_csv(rows: Iterable[dict], columns: list[tuple[str, str]]) -> str:
    """Converte linhas em CSV (separador ";" para abrir corretamente no Excel pt-BR) com BOM UTF-8.
    `columns` = [(chave, rótulo), ...]."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow([_csv_cell(label) for _, label in columns])
    for row in rows:
        writer.writerow([_csv_cell(row.get(key)) for key, _ in columns])
    return "﻿" + buf.getvalue()
