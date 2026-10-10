"""Consulta de CEP (ViaCEP → BrasilAPI) com cache em CepCache. Sem dependência de request (usável no worker)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

from .models import CepCache

logger = logging.getLogger(__name__)


def normalize_cep(value: str | None) -> str | None:
    d = re.sub(r"\D", "", value or "")
    return d if len(d) == 8 and d != "00000000" else None


def format_cep(value: str | None) -> str:
    d = re.sub(r"\D", "", value or "")
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else (value or "")


@dataclass
class CepInfo:
    cep: str
    street: str = ""
    neighborhood: str = ""
    city: str = ""
    state: str = ""
    latitude: float | None = None
    longitude: float | None = None

    def as_dict(self) -> dict:
        return {
            "cep": self.cep,
            "street": self.street,
            "neighborhood": self.neighborhood,
            "city": self.city,
            "state": self.state,
        }


def _clean(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _get_json(url: str, timeout: float = 6.0):
    try:
        res = httpx.get(url, timeout=timeout, headers={"Accept": "application/json"}, follow_redirects=True)
        if res.status_code != 200:
            return None
        return res.json()
    except (httpx.HTTPError, ValueError):
        return None


def from_viacep(cep: str) -> CepInfo | None:
    data = _get_json(f"https://viacep.com.br/ws/{cep}/json/")
    if not isinstance(data, dict) or data.get("erro"):
        return None
    return CepInfo(
        cep=cep,
        street=_clean(data.get("logradouro")),
        neighborhood=_clean(data.get("bairro")),
        city=_clean(data.get("localidade")),
        state=_clean(data.get("uf")),
    )


def from_brasilapi(cep: str) -> CepInfo | None:
    """BrasilAPI v2 devolve também coordenadas do CEP (quando conhecidas)."""
    data = _get_json(f"https://brasilapi.com.br/api/cep/v2/{cep}")
    if not isinstance(data, dict) or not data.get("cep"):
        return None
    coords = ((data.get("location") or {}).get("coordinates")) or {}
    try:
        lat, lng = float(coords.get("latitude")), float(coords.get("longitude"))
    except (TypeError, ValueError):
        lat = lng = None
    if lat == 0 or lng == 0:
        lat = lng = None
    return CepInfo(
        cep=cep,
        street=_clean(data.get("street")),
        neighborhood=_clean(data.get("neighborhood")),
        city=_clean(data.get("city")),
        state=_clean(data.get("state")),
        latitude=lat,
        longitude=lng,
    )


def lookup_cep(value: str | None) -> CepInfo | None:
    """Endereço de um CEP. None se o CEP não existir ou os serviços estiverem indisponíveis."""
    cep = normalize_cep(value)
    if not cep:
        return None
    cached = CepCache.objects.filter(key=cep).first()
    if cached and (cached.city or cached.street):
        return CepInfo(cep, cached.street, cached.neighborhood, cached.city, cached.state)

    info = from_viacep(cep) or from_brasilapi(cep)
    if not info:
        return None
    CepCache.objects.update_or_create(
        key=cep,
        defaults={"street": info.street, "neighborhood": info.neighborhood, "city": info.city, "state": info.state},
    )
    return info
