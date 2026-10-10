"""Geocodificação de eleitores para o mapa. Coordenadas no nível do CEP/logradouro (não do imóvel),
o que também protege a privacidade do eleitor.

Ordem: cache → BrasilAPI (coordenadas do CEP) → Nominatim (rua) → Nominatim (CEP) → Nominatim (bairro) → cidade.
Sem dependência de request (usado pelo worker e após cadastros).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import httpx
from django.conf import settings

from apps.core.constants import GeoStatus
from apps.core.utils import slugify

from .cep import from_brasilapi, normalize_cep
from .models import CepCache

logger = logging.getLogger(__name__)

_MISSING = object()  # nunca tentado (diferente de "tentado e falhou" = None)


@dataclass
class GeoPoint:
    latitude: float
    longitude: float
    precision: str  # "OK" | "APPROXIMATE"
    source: str


# --- Nominatim: no máximo 1 requisição por segundo (política de uso do OSM) -------------------------
_nominatim_lock = threading.Lock()
_last_nominatim_at = 0.0


def _nominatim(**params) -> tuple[float, float] | None:
    global _last_nominatim_at
    with _nominatim_lock:
        wait = _last_nominatim_at + 1.1 - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_nominatim_at = time.monotonic()
        query = {"format": "jsonv2", "limit": "1", "countrycodes": "br", **params}
        try:
            res = httpx.get(
                "https://nominatim.openstreetmap.org/search",
                params=query,
                headers={"User-Agent": settings.GEOCODER_USER_AGENT, "Accept-Language": "pt-BR"},
                timeout=8.0,
            )
            if res.status_code != 200:
                return None
            data = res.json()
            if not data:
                return None
            return float(data[0]["lat"]), float(data[0]["lon"])
        except (httpx.HTTPError, ValueError, KeyError, IndexError):
            return None


def _area_key(city: str, state: str, neighborhood: str = "") -> str:
    key = f"A:{slugify(state)}:{slugify(city)}"
    return f"{key}:{slugify(neighborhood)}" if neighborhood else key


def _cached_point(key: str):
    row = CepCache.objects.filter(key=key).first()
    if row is None or not row.geo_source:
        return _MISSING
    if row.latitude is None or row.longitude is None:
        return None
    precise = row.geo_source in ("brasilapi", "nominatim")
    return GeoPoint(row.latitude, row.longitude, "OK" if precise else "APPROXIMATE", row.geo_source)


def _save_point(key: str, point: GeoPoint | None, *, street="", neighborhood="", city="", state="") -> None:
    CepCache.objects.update_or_create(
        key=key,
        defaults={
            "latitude": point.latitude if point else None,
            "longitude": point.longitude if point else None,
            "geo_source": point.source if point else "none",
            "street": street or "",
            "neighborhood": neighborhood or "",
            "city": city or "",
            "state": state or "",
        },
    )


def _geocode_area(city: str, state: str, neighborhood: str = "") -> GeoPoint | None:
    key = _area_key(city, state, neighborhood)
    cached = _cached_point(key)
    if cached is not _MISSING:
        return cached
    q = ", ".join(p for p in (neighborhood, city, state, "Brasil") if p)
    found = _nominatim(q=q)
    point = (
        GeoPoint(found[0], found[1], "APPROXIMATE", "nominatim-bairro" if neighborhood else "nominatim-cidade")
        if found
        else None
    )
    _save_point(key, point, neighborhood=neighborhood, city=city, state=state)
    return point


def geocode_address(*, cep="", street="", neighborhood="", city="", state="") -> GeoPoint | None:
    """Geocodifica um endereço. None se nada for encontrado."""
    cep_n = normalize_cep(cep)
    if cep_n:
        cached = _cached_point(cep_n)
        if isinstance(cached, GeoPoint):
            return cached
        if cached is _MISSING:
            point: GeoPoint | None = None
            br = from_brasilapi(cep_n)
            if br and br.latitude is not None and br.longitude is not None:
                point = GeoPoint(br.latitude, br.longitude, "OK", "brasilapi")
            st = street or (br.street if br else "")
            ct = city or (br.city if br else "")
            uf = state or (br.state if br else "")
            if not point and st and ct:
                found = _nominatim(street=st, city=ct, state=uf, country="Brasil")
                if found:
                    point = GeoPoint(found[0], found[1], "OK", "nominatim")
            if not point:
                found = _nominatim(postalcode=f"{cep_n[:5]}-{cep_n[5:]}", country="Brasil")
                if found:
                    point = GeoPoint(found[0], found[1], "OK", "nominatim")
            _save_point(
                cep_n,
                point,
                street=st,
                neighborhood=neighborhood or (br.neighborhood if br else ""),
                city=ct,
                state=uf,
            )
            if point:
                return point

    if city and neighborhood:
        p = _geocode_area(city, state, neighborhood)
        if p:
            return p
    if city:
        return _geocode_area(city, state)
    return None


def geocode_voter(voter_id) -> None:
    """Geocodifica um eleitor e grava latitude/longitude/geo_status."""
    from apps.voters.models import Voter

    voter = Voter.objects.filter(pk=voter_id).first()
    if voter is None:
        return
    point = geocode_address(
        cep=voter.cep, street=voter.street, neighborhood=voter.neighborhood, city=voter.city, state=voter.state
    )
    if point:
        Voter.objects.filter(pk=voter.pk).update(
            latitude=point.latitude, longitude=point.longitude, geo_status=point.precision
        )
    else:
        Voter.objects.filter(pk=voter.pk).update(geo_status=GeoStatus.FAILED)


def geocode_voter_in_background(voter_id) -> None:
    """Dispara a geocodificação sem bloquear a resposta (thread). Em testes/worker prefira chamar geocode_voter."""

    def run():
        try:
            geocode_voter(voter_id)
        except Exception:  # noqa: BLE001
            logger.exception("Falha ao geocodificar eleitor")
        finally:
            from django.db import connection

            connection.close()

    threading.Thread(target=run, daemon=True).start()


def process_pending_geocoding(limit: int = 10) -> int:
    """Processa eleitores com geo_status PENDING (worker). Retorna quantos processou."""
    from apps.voters.models import Voter

    ids = list(
        Voter.objects.filter(geo_status=GeoStatus.PENDING).order_by("created_at").values_list("id", flat=True)[:limit]
    )
    for voter_id in ids:
        try:
            geocode_voter(voter_id)
        except Exception:  # noqa: BLE001
            logger.exception("Falha ao geocodificar eleitor")
            Voter.objects.filter(pk=voter_id).update(geo_status=GeoStatus.FAILED)
    return len(ids)
