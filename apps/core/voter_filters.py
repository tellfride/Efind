"""Filtros de apoiadores compartilhados por lista, mapa, dashboards e público dos disparos.

Um filtro é um dict simples e serializável em JSON (cabe em Broadcast.filters / widget.config):

    {"q": "ana", "neighborhoods": ["Centro"], "cities": [...], "registered_by_ids": [uuid...],
     "coordinator_ids": [uuid...], "genders": ["F"], "support_levels": [...], "sources": [...],
     "tags": ["saude"], "electoral_zones": ["12"], "age_min": 18, "age_max": 60,
     "created_from": "2026-01-01", "created_to": "2026-12-31", "has_geo": True, "messageable": True}

O queryset é montado em apps.core.access.voters_queryset(user, filters), que SEMPRE aplica o escopo do usuário.
Este módulo é puro (sem banco): interpreta a URL e serializa de volta.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from typing import Any

from .constants import Gender, SupportLevel, VoterSource

LIST_KEYS = (
    "neighborhoods",
    "cities",
    "registered_by_ids",
    "coordinator_ids",
    "genders",
    "support_levels",
    "sources",
    "tags",
    "electoral_zones",
)
INT_KEYS = ("age_min", "age_max")
DATE_KEYS = ("created_from", "created_to")
BOOL_KEYS = ("has_geo", "messageable")
ALL_KEYS = ("q", *LIST_KEYS, *INT_KEYS, *DATE_KEYS, *BOOL_KEYS)

# Nome do parâmetro de URL de cada filtro (pt-BR, curto)
URL_PARAMS = {
    "q": "q",
    "neighborhoods": "bairro",
    "cities": "cidade",
    "registered_by_ids": "cabo",
    "coordinator_ids": "coord",
    "genders": "genero",
    "support_levels": "apoio",
    "sources": "origem",
    "tags": "tag",
    "electoral_zones": "zona",
    "age_min": "idade_min",
    "age_max": "idade_max",
    "created_from": "de",
    "created_to": "ate",
    "has_geo": "geo",
    "messageable": "whatsapp",
}

_ENUMS = {
    "genders": {c.value for c in Gender},
    "support_levels": {c.value for c in SupportLevel},
    "sources": {c.value for c in VoterSource},
}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _clean_str(v: Any, max_len: int = 120) -> str:
    return str(v).strip()[:max_len]


def _valid_uuid(v: str) -> bool:
    try:
        uuid.UUID(v)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def sanitize_voter_filters(raw: Mapping[str, Any] | None) -> dict:
    """Valida/normaliza um dict de filtros (de JSON salvo ou de entrada). Descarta o que for inválido."""
    out: dict[str, Any] = {}
    raw = raw or {}
    q = _clean_str(raw.get("q") or "", 100)
    if q:
        out["q"] = q
    for key in LIST_KEYS:
        values = raw.get(key)
        if not isinstance(values, (list, tuple)):
            continue
        items = [_clean_str(v) for v in values if v not in (None, "")][:200]
        if key in _ENUMS:
            items = [i for i in items if i in _ENUMS[key]]
        elif key in ("registered_by_ids", "coordinator_ids"):
            items = [i for i in items if _valid_uuid(i)]
        if items:
            out[key] = list(dict.fromkeys(items))
    for key in INT_KEYS:
        v = raw.get(key)
        if v in (None, ""):
            continue
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if 0 <= n <= 130:
            out[key] = n
    for key in DATE_KEYS:
        v = raw.get(key)
        if isinstance(v, str) and _DATE_RE.match(v):
            out[key] = v
    for key in BOOL_KEYS:
        v = raw.get(key)
        if isinstance(v, bool):
            out[key] = v
    return out


def parse_voter_filters(params) -> dict:
    """Lê os filtros da URL (QueryDict/dict). Valores inválidos são ignorados."""
    getlist = params.getlist if hasattr(params, "getlist") else (lambda k: _as_list(params.get(k)))
    raw: dict[str, Any] = {}
    q = (params.get(URL_PARAMS["q"]) or "").strip()
    if q:
        raw["q"] = q
    for key in LIST_KEYS:
        values = [v for v in getlist(URL_PARAMS[key]) if v]
        if values:
            raw[key] = values
    for key in INT_KEYS + DATE_KEYS:
        v = params.get(URL_PARAMS[key])
        if v:
            raw[key] = v
    for key in BOOL_KEYS:
        v = params.get(URL_PARAMS[key])
        if v in ("1", "true"):
            raw[key] = True
        elif v in ("0", "false"):
            raw[key] = False
    return sanitize_voter_filters(raw)


def _as_list(v) -> list:
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def voter_filters_to_params(filters: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Filtros → lista de pares (parâmetro, valor) para montar querystrings (urlencode)."""
    pairs: list[tuple[str, str]] = []
    for key, value in sanitize_voter_filters(filters).items():
        param = URL_PARAMS[key]
        if isinstance(value, list):
            pairs.extend((param, str(v)) for v in value)
        elif isinstance(value, bool):
            pairs.append((param, "1" if value else "0"))
        else:
            pairs.append((param, str(value)))
    return pairs


def count_active_filters(filters: Mapping[str, Any]) -> int:
    return len(sanitize_voter_filters(filters))


def clean_voter_filters(filters: Mapping[str, Any] | None) -> dict:
    """Remove chaves vazias/inválidas (use antes de salvar em Broadcast.filters ou em config de widget)."""
    return sanitize_voter_filters(filters)
