"""Criptografia simétrica (AES-256-GCM) para credenciais de provedores de WhatsApp.
Formato: v1:<iv base64>:<tag base64>:<dados base64>
"""

from __future__ import annotations

import base64
import json
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings


def _key() -> bytes:
    raw = getattr(settings, "ENCRYPTION_KEY", "")
    if not raw:
        raise RuntimeError("ENCRYPTION_KEY não configurada (veja .env.example)")
    key = base64.b64decode(raw)
    if len(key) != 32:
        raise RuntimeError("ENCRYPTION_KEY deve ter 32 bytes em base64")
    return key


def encrypt_string(plain: str) -> str:
    iv = secrets.token_bytes(12)
    sealed = AESGCM(_key()).encrypt(iv, plain.encode("utf-8"), None)  # dados + tag(16)
    data, tag = sealed[:-16], sealed[-16:]
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"v1:{b64(iv)}:{b64(tag)}:{b64(data)}"


def decrypt_string(payload: str) -> str:
    try:
        version, iv_b64, tag_b64, data_b64 = payload.split(":")
    except ValueError as exc:
        raise ValueError("Formato de dado criptografado inválido") from exc
    if version != "v1":
        raise ValueError("Versão de criptografia desconhecida")
    iv, tag, data = (base64.b64decode(x) for x in (iv_b64, tag_b64, data_b64))
    return AESGCM(_key()).decrypt(iv, data + tag, None).decode("utf-8")


def encrypt_json(value) -> str:
    return encrypt_string(json.dumps(value, ensure_ascii=False))


def decrypt_json(payload: str):
    return json.loads(decrypt_string(payload))


def random_token(nbytes: int = 24) -> str:
    """Token aleatório seguro para URLs (base64url)."""
    return secrets.token_urlsafe(nbytes)


_INVITE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # sem caracteres ambíguos


def random_invite_code(length: int = 8) -> str:
    """Código curto e legível para links de cadastro."""
    return "".join(secrets.choice(_INVITE_ALPHABET) for _ in range(length))


def mask_secret(value: str | None, visible: int = 4) -> str:
    """Mascara um segredo para exibição ("EAAG••••••9xZ")."""
    if not value:
        return ""
    if len(value) <= visible * 2:
        return "•" * len(value)
    return f"{value[:visible]}{'•' * 6}{value[-visible:]}"
