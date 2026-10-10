"""Fixtures compartilhadas dos testes do módulo portal (sem rede, SQLite em memória)."""

from __future__ import annotations

import base64
import struct
import zlib

from django.test import Client, override_settings

from apps.accounts.models import RolePermission, User
from apps.campaigns.bootstrap import bootstrap_campaign
from apps.campaigns.models import Campaign
from apps.core.constants import Role

PASSWORD = "Senha@12345"

# Hash rápido só nos testes (PBKDF2 torna cada login de teste lento)
fast_hashing = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


def make_campaign(slug: str, **extra) -> Campaign:
    campaign = Campaign.objects.create(
        slug=slug,
        candidate_name=extra.pop("candidate_name", slug.title() + " da Silva"),
        ballot_name=extra.pop("ballot_name", slug.title()),
        office="VEREADOR",
        election_year=2026,
        **extra,
    )
    bootstrap_campaign(campaign)
    return campaign


def make_user(campaign, email: str, role: str, parent=None, **extra) -> User:
    return User.objects.create_user(
        email, PASSWORD, name=extra.pop("name", email.split("@")[0]), role=role, campaign=campaign, parent=parent, **extra
    )


def grant(campaign, role: str, module: str, **perms) -> None:
    """Ajusta a linha RolePermission do papel (ex.: grant(c, Role.COORDENADOR, "auditoria", can_view=True))."""
    updated = RolePermission.objects.filter(campaign=campaign, role=role, module=module).update(**perms)
    assert updated == 1, "linha de permissão não encontrada"


def login(email: str, password: str = PASSWORD, **client_kwargs) -> Client:
    client = Client(**client_kwargs)
    assert client.login(email=email, password=password), "login de teste falhou"
    return client


# --- Imagens mínimas válidas (somente cabeçalhos/estrutura necessários) -----------------------------------
def png_bytes(width: int = 2, height: int = 2) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def jpeg_bytes(width: int = 8, height: int = 8) -> bytes:
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xc0\x00\x11\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
        + b"\xff\xd9"
    )


def webp_bytes(width: int = 8, height: int = 8) -> bytes:
    return (
        b"RIFF"
        + struct.pack("<I", 22)
        + b"WEBP"
        + b"VP8X"
        + struct.pack("<I", 10)
        + b"\x00\x00\x00\x00"
        + (width - 1).to_bytes(3, "little")
        + (height - 1).to_bytes(3, "little")
    )


def data_url(raw: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def identity_payload(**overrides) -> dict:
    """POST válido do cartão "Identidade" (altere só o que o teste precisa)."""
    data = {
        "section": "identity",
        "candidate_name": "Maria Aparecida Souza",
        "ballot_name": "Dra. Maria",
        "ballot_number": "12345",
        "party": "PXX",
        "office": "VEREADOR",
        "election_year": "2026",
        "city": "Campinas",
        "state": "SP",
        "voter_goal": "5000",
        "primary_color": "#112233",
        "logo_action": "keep",
        "logo_data": "",
    }
    data.update(overrides)
    return data


def public_form_payload(**overrides) -> dict:
    """POST válido do cartão "Formulário público"."""
    data = {
        "section": "public_form",
        "form_title": "Junte-se a nós",
        "form_message": "Receba as novidades da campanha.",
        "consent_text": "",
        "privacy_contact": "Maria · privacidade@exemplo.com.br",
        "config_email": "optional",
        "config_birth_date": "hidden",
        "config_gender": "optional",
        "config_address": "required",
        "config_electoral": "hidden",
    }
    data.update(overrides)
    return data


__all__ = [
    "PASSWORD",
    "Role",
    "data_url",
    "fast_hashing",
    "grant",
    "identity_payload",
    "jpeg_bytes",
    "login",
    "make_campaign",
    "make_user",
    "png_bytes",
    "public_form_payload",
    "webp_bytes",
]
