"""Telefones brasileiros. Armazenamos só dígitos com DDI 55: 55 + DDD (2) + número (8 ou 9)."""

from __future__ import annotations

import re
from urllib.parse import quote

VALID_DDDS = frozenset(
    {
        11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 24, 27, 28, 31, 32, 33, 34, 35, 37, 38, 41, 42, 43, 44, 45, 46,
        47, 48, 49, 51, 53, 54, 55, 61, 62, 63, 64, 65, 66, 67, 68, 69, 71, 73, 74, 75, 77, 79, 81, 82, 83, 84, 85,
        86, 87, 88, 89, 91, 92, 93, 94, 95, 96, 97, 98, 99,
    }
)  # fmt: skip


def normalize_br_phone(value: str | None) -> str | None:
    """Normaliza para "55DDNNNNNNNNN". Aceita "(11) 98765-4321", "+55 11 98765 4321", "011987654321"...
    Retorna None se não for um telefone brasileiro válido."""
    if not value:
        return None
    d = re.sub(r"\D", "", value)
    if d.startswith("00"):  # prefixo internacional 00 55 ...
        d = d[2:]
    elif d.startswith("0") and len(d) in (11, 12):  # 0 + DDD + número
        d = d[1:]
    if len(d) in (12, 13):
        if not d.startswith("55"):
            return None
        d = d[2:]
    if len(d) not in (10, 11):
        return None
    if int(d[:2]) not in VALID_DDDS:
        return None
    number = d[2:]
    if len(number) == 9 and number[0] != "9":  # celular tem 9 dígitos começando com 9
        return None
    if len(number) == 8 and number[0] not in "23456789":
        return None
    return f"55{d}"


def is_valid_br_phone(value: str | None) -> bool:
    return normalize_br_phone(value) is not None


def format_phone(stored: str | None) -> str:
    """"5511987654321" → "(11) 98765-4321" """
    if not stored:
        return ""
    d = re.sub(r"\D", "", stored)
    if re.fullmatch(r"55\d{10,11}", d):
        d = d[2:]
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return stored


def whatsapp_link(stored: str, text: str | None = None) -> str:
    """Link wa.me para abrir uma conversa."""
    digits = re.sub(r"\D", "", stored)
    base = f"https://wa.me/{digits}"
    return f"{base}?text={quote(text)}" if text else base
