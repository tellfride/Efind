"""Geocodificação de apoiadores para o mapa. Coordenadas no nível do CEP/logradouro (não do imóvel), o que também
protege a privacidade do apoiador: o número da casa nunca é enviado aos serviços externos.

Princípio: NENHUMA coordenada é aceita sem conferir que cai dentro do bairro (ou da cidade) do apoiador. Fontes externas
erram com frequência — ex.: o BrasilAPI devolve o mesmo ponto do centro do Rio para todos os CEPs da Av. Brasil, e uma
busca só pelo nome dessa avenida (58 km) cai em Campo Grande. Por isso a ordem é:

  1. rua dentro da caixa do bairro (Nominatim com viewbox + bounded)          → precisão OK
  2. coordenada do CEP no BrasilAPI, SE estiver dentro do bairro               → precisão OK
  3. código postal no Nominatim, SE estiver dentro do bairro                   → precisão OK
  4. centro do bairro                                                          → APROXIMADO
  5. centro da cidade                                                          → APROXIMADO

Sem dependência de request (usado pelo worker, pelo comando regeocode e após cadastros).
"""

from __future__ import annotations

import hashlib
import logging
import math
import threading
import time
from dataclasses import dataclass

import httpx
from django.conf import settings

from apps.core.constants import GeoStatus
from apps.core.utils import slugify

from .cep import from_brasilapi, lookup_cep, normalize_cep
from .models import CepCache

logger = logging.getLogger(__name__)

_MISSING = object()  # nunca tentado (diferente de "tentado e sem resultado" = None)

PRECISE_SOURCES = {"nominatim-rua", "brasilapi", "nominatim-cep"}


@dataclass
class GeoPoint:
    latitude: float
    longitude: float
    precision: str  # "OK" | "APPROXIMATE"
    source: str


@dataclass
class Area:
    """Centro e caixa (sul, oeste, norte, leste) de um bairro ou de uma cidade."""

    lat: float
    lng: float
    bbox: tuple[float, float, float, float] | None
    level: str  # "bairro" | "cidade"

    def box(self) -> tuple[float, float, float, float]:
        """Caixa de validação: a do Nominatim ampliada (15% + 300 m), com tamanho mínimo por nível."""
        min_km = 1.5 if self.level == "bairro" else 10.0
        lat_km = 1 / 111.0
        lng_km = 1 / (111.0 * max(0.2, math.cos(math.radians(self.lat))))
        s, w, n, e = self.bbox or (self.lat, self.lng, self.lat, self.lng)
        pad_lat = (n - s) * 0.15 + 0.3 * lat_km
        pad_lng = (e - w) * 0.15 + 0.3 * lng_km
        s, n, w, e = s - pad_lat, n + pad_lat, w - pad_lng, e + pad_lng
        half_lat, half_lng = min_km * lat_km, min_km * lng_km
        s, n = min(s, self.lat - half_lat), max(n, self.lat + half_lat)
        w, e = min(w, self.lng - half_lng), max(e, self.lng + half_lng)
        return s, w, n, e

    def contains(self, lat: float, lng: float) -> bool:
        s, w, n, e = self.box()
        return s <= lat <= n and w <= lng <= e


# --- Nominatim: no máximo 1 requisição por segundo (política de uso do OSM) -------------------------
_nominatim_lock = threading.Lock()
_last_nominatim_at = 0.0


def _nominatim(**params) -> list[dict] | None:
    """Resultados do Nominatim. [] = o serviço respondeu e não achou nada; None = falha de rede/serviço (não cachear)."""
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
            return data if isinstance(data, list) else None
        except (httpx.HTTPError, ValueError):
            return None


def _result_point(result: dict) -> tuple[float, float] | None:
    try:
        return float(result["lat"]), float(result["lon"])
    except (KeyError, TypeError, ValueError):
        return None


def _result_bbox(result: dict) -> tuple[float, float, float, float] | None:
    """boundingbox do Nominatim = [sul, norte, oeste, leste] (strings) → (sul, oeste, norte, leste)."""
    try:
        s, n, w, e = (float(x) for x in result["boundingbox"])
        return s, w, n, e
    except (KeyError, TypeError, ValueError):
        return None


def _fmt_bbox(bbox) -> str:
    return ",".join(f"{v:.6f}" for v in bbox) if bbox else ""


def _parse_bbox(text: str):
    try:
        s, w, n, e = (float(x) for x in text.split(","))
        return s, w, n, e
    except (AttributeError, ValueError):
        return None


# --- Áreas (cidade/bairro), com cache -----------------------------------------------------------------
def _cap(key: str) -> str:
    """A chave do cache tem no máximo 120 caracteres: chaves longas viram prefixo + hash."""
    return key if len(key) <= 120 else f"{key[:90]}~{hashlib.sha1(key.encode()).hexdigest()[:20]}"


def _area_key(city: str, state: str, neighborhood: str = "") -> str:
    key = f"A:{slugify(state)}:{slugify(city)}"
    return _cap(f"{key}:{slugify(neighborhood)}" if neighborhood else key)


def _load_area(key: str, level: str):
    """Area | None (tentado sem resultado) | _MISSING (nunca tentado ou entrada antiga sem caixa)."""
    row = CepCache.objects.filter(key=key).first()
    if row is None or not row.geo_source:
        return _MISSING
    if row.latitude is None or row.longitude is None:
        return None
    bbox = _parse_bbox(row.bbox)
    if bbox is None:  # entrada da versão anterior (só centro): refaz para obter a caixa
        return _MISSING
    return Area(row.latitude, row.longitude, bbox, level)


def _save_area(key: str, area: Area | None, level: str, **address) -> None:
    CepCache.objects.update_or_create(
        key=key,
        defaults={
            "latitude": area.lat if area else None,
            "longitude": area.lng if area else None,
            "bbox": _fmt_bbox(area.bbox) if area else "",
            "geo_source": f"nominatim-{level}" if area else "none",
            "city": address.get("city", "") or "",
            "state": address.get("state", "") or "",
            "neighborhood": address.get("neighborhood", "") or "",
        },
    )


def _find_area(city: str, state: str, neighborhood: str, city_area: Area | None) -> Area | None | object:
    """Procura a área no Nominatim. Devolve Area, None (não achou) ou _MISSING (falha de rede: não cachear)."""
    level = "bairro" if neighborhood else "cidade"
    q = ", ".join(p for p in (neighborhood, city, state, "Brasil") if p)
    results = _nominatim(q=q)
    if results is None:
        return _MISSING
    for r in results:
        point = _result_point(r)
        if not point:
            continue
        area = Area(point[0], point[1], _result_bbox(r), level)
        # um bairro só vale se estiver dentro da cidade (evita homônimos em outras cidades)
        if level == "bairro" and city_area is not None and not city_area.contains(point[0], point[1]):
            continue
        return area
    return None


def _get_area(city: str, state: str, neighborhood: str = "") -> tuple[Area | None, bool]:
    """(área | None, falha_de_rede). Falha de rede nunca é gravada no cache como resposta final."""
    if not city:
        return None, False
    level = "bairro" if neighborhood else "cidade"
    city_area, city_failed = _get_area(city, state) if neighborhood else (None, False)
    if neighborhood and city_failed:
        return None, True  # sem a cidade não dá para validar o bairro (evita homônimos em outras cidades)
    key = _area_key(city, state, neighborhood)
    cached = _load_area(key, level)
    if cached is not _MISSING:
        return cached, False
    found = _find_area(city, state, neighborhood, city_area)
    if found is _MISSING:
        return None, True
    _save_area(key, found, level, city=city, state=state, neighborhood=neighborhood)
    return found, False


def get_area(city: str, state: str, neighborhood: str = "") -> Area | None:
    """Área (bairro ou cidade) com cache. None se não encontrada ou se o serviço estiver indisponível."""
    return _get_area(city, state, neighborhood)[0]


# --- Pontos (CEP/logradouro), com cache ---------------------------------------------------------------
def _point_key(cep: str, street: str, neighborhood: str, city: str, state: str) -> str:
    if cep:
        return _cap(f"P:{cep}:{slugify(neighborhood)}")
    return _cap(f"S:{slugify(state)}:{slugify(city)}:{slugify(neighborhood)}:{slugify(street)}")


def _cached_point(key: str):
    row = CepCache.objects.filter(key=key).first()
    if row is None or not row.geo_source:
        return _MISSING
    if row.latitude is None or row.longitude is None:
        return None
    precise = row.geo_source in PRECISE_SOURCES
    return GeoPoint(row.latitude, row.longitude, "OK" if precise else "APPROXIMATE", row.geo_source)


def _save_point(key: str, point: GeoPoint | None, *, street="", neighborhood="", city="", state="") -> None:
    CepCache.objects.update_or_create(
        key=key,
        defaults={
            "latitude": point.latitude if point else None,
            "longitude": point.longitude if point else None,
            "geo_source": point.source if point else "none",
            "bbox": "",
            "street": street or "",
            "neighborhood": neighborhood or "",
            "city": city or "",
            "state": state or "",
        },
    )


def _street_in_area(street: str, area: Area, city: str, state: str) -> tuple[GeoPoint | None, bool]:
    """Rua dentro da caixa da área. Devolve (ponto, houve_falha_de_rede)."""
    s, w, n, e = area.box()
    results = _nominatim(street=street, city=city, state=state, country="Brasil", viewbox=f"{w},{n},{e},{s}", bounded="1")
    if results is None:
        return None, True
    for r in results:
        point = _result_point(r)
        if point and area.contains(*point):
            return GeoPoint(point[0], point[1], "OK", "nominatim-rua"), False
    return None, False


def geocode_address(*, cep="", street="", neighborhood="", city="", state="") -> GeoPoint | None:
    """Geocodifica um endereço (nível de rua/CEP). None se nada foi encontrado ou se os serviços falharam."""
    cep_n = normalize_cep(cep) or ""
    if cep_n and not (street and neighborhood and city):  # completa o que faltar com o endereço oficial do CEP
        info = lookup_cep(cep_n)
        if info:
            street, neighborhood = street or info.street, neighborhood or info.neighborhood
            city, state = city or info.city, state or info.state
    if not city:
        return None

    key = _point_key(cep_n, street, neighborhood, city, state)
    cached = _cached_point(key)
    if cached is not _MISSING:
        return cached

    area, area_failed = _get_area(city, state, neighborhood) if neighborhood else (None, False)
    city_area, city_failed = _get_area(city, state)
    check = area or city_area  # com bairro conhecido valida no bairro; senão, na cidade
    network_failed = area_failed or city_failed
    point: GeoPoint | None = None

    if check is not None and street:
        point, failed = _street_in_area(street, check, city, state)
        network_failed = network_failed or failed
    if point is None and check is not None and cep_n:
        br = from_brasilapi(cep_n)
        if br and br.latitude is not None and br.longitude is not None and check.contains(br.latitude, br.longitude):
            point = GeoPoint(br.latitude, br.longitude, "OK", "brasilapi")
    if point is None and check is not None and cep_n:
        results = _nominatim(postalcode=f"{cep_n[:5]}-{cep_n[5:]}", country="Brasil")
        if results is None:
            network_failed = True
        else:
            for r in results:
                p = _result_point(r)
                if p and check.contains(*p):
                    point = GeoPoint(p[0], p[1], "OK", "nominatim-cep")
                    break
    if point is None and area is not None:
        point = GeoPoint(area.lat, area.lng, "APPROXIMATE", "nominatim-bairro")
    if point is None and city_area is not None:
        point = GeoPoint(city_area.lat, city_area.lng, "APPROXIMATE", "nominatim-cidade")

    if point is not None or not network_failed:
        _save_point(key, point, street=street, neighborhood=neighborhood, city=city, state=state)
    return point


def geocode_voter(voter_id) -> None:
    """Geocodifica um apoiador e grava latitude/longitude/geo_status."""
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
            logger.exception("Falha ao geocodificar apoiador")
        finally:
            from django.db import connection

            connection.close()

    threading.Thread(target=run, daemon=True).start()


def process_pending_geocoding(limit: int = 10, campaign_id=None) -> int:
    """Processa apoiadores com geo_status PENDING (worker). `campaign_id` restringe a uma campanha. Retorna quantos processou."""
    from apps.voters.models import Voter

    qs = Voter.objects.filter(geo_status=GeoStatus.PENDING)
    if campaign_id is not None:
        qs = qs.filter(campaign_id=campaign_id)
    ids = list(qs.order_by("created_at").values_list("id", flat=True)[:limit])
    for voter_id in ids:
        try:
            geocode_voter(voter_id)
        except Exception:  # noqa: BLE001
            logger.exception("Falha ao geocodificar apoiador")
            Voter.objects.filter(pk=voter_id).update(geo_status=GeoStatus.FAILED)
    return len(ids)
