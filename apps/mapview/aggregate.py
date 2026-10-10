"""Agregação dos dados do mapa (lógica pura, sem banco).

Recebe as linhas mínimas dos eleitores JÁ filtradas pelo escopo do usuário (veja `data.py`) e monta totais,
bairros (centroide), pontos (sem dados pessoais) e limites do mapa.

Cada linha é um mapeamento com as chaves:
    id, latitude, longitude, geo_status, neighborhood, city, support_level, messageable, registered_by_id

Privacidade: nomes, telefones e e-mails de eleitores NUNCA entram aqui; os pontos levam apenas id e coordenadas.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar

from apps.core.constants import GeoStatus, SupportLevel
from apps.core.utils import normalize_text

from .scale import build_color_scale, color_for_count, radius_for_count

T = TypeVar("T")

# Limite de pontos individuais enviados ao navegador
MAP_POINT_LIMIT = 20_000
# Quantos membros aparecem em "quem mais cadastrou" de cada bairro
TOP_MEMBERS_PER_NEIGHBORHOOD = 3
UNKNOWN_NEIGHBORHOOD = "Bairro não informado"
UNKNOWN_MEMBER = "Membro da equipe"

_SPACES = re.compile(r"\s+")


def valid_coordinates(lat: Any, lng: Any) -> bool:
    """Coordenadas utilizáveis: números finitos, dentro do globo e diferentes de (0, 0)."""
    if lat is None or lng is None or isinstance(lat, bool) or isinstance(lng, bool):
        return False
    try:
        lat_f, lng_f = float(lat), float(lng)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(lat_f) and math.isfinite(lng_f)):
        return False
    if not (-90 <= lat_f <= 90 and -180 <= lng_f <= 180):
        return False
    return not (lat_f == 0 and lng_f == 0)


def clean_text(value: Any) -> str:
    """Remove espaços nas pontas e repetidos. Vazio → ''."""
    return _SPACES.sub(" ", str(value or "")).strip()


def neighborhood_key(name: str, city: str) -> str:
    """Chave bairro+cidade (separador de unidade — não aparece em nomes digitados)."""
    return f"{name}\x1f{city}"


def sample_points(items: Sequence[T], limit: int) -> list[T]:
    """Amostra uniforme (índices igualmente espaçados), preservando a ordem. Determinística."""
    if limit <= 0:
        return []
    if len(items) <= limit:
        return list(items)
    step = len(items) / limit
    return [items[int(i * step)] for i in range(limit)]


@dataclass(slots=True)
class _Group:
    name: str
    city: str
    count: int = 0
    mapped: int = 0
    lat_sum: float = 0.0
    lng_sum: float = 0.0
    messageable: int = 0
    supporters: int = 0
    members: Counter = field(default_factory=Counter)


def _by_count_then_name(item: Mapping[str, Any]) -> tuple:
    return (-item["count"], normalize_text(item["name"]), item["name"], item["city"])


def aggregate_map_data(
    rows: Iterable[Mapping[str, Any]],
    *,
    member_names: Mapping[Any, str],
    can_view_voters: bool,
    point_limit: int | None = None,
    top_members: int = TOP_MEMBERS_PER_NEIGHBORHOOD,
) -> dict:
    """Linhas de eleitores → dados do mapa (dict serializável em JSON, chaves em snake_case).

    - `member_names`: id → nome de quem cadastrou (o escopo do usuário já garante que são membros visíveis).
    - Bairros com ao menos um eleitor localizado vão em `neighborhoods` (centroide = média das coordenadas);
      os demais, em `neighborhoods_without_geo`.
    """
    limit = MAP_POINT_LIMIT if point_limit is None else point_limit

    groups: dict[str, _Group] = {}
    geocoded: list[tuple[Any, float, float]] = []
    total = 0
    approximate = 0
    min_lat = min_lng = math.inf
    max_lat = max_lng = -math.inf

    for row in rows:
        total += 1
        name = clean_text(row.get("neighborhood"))
        city = clean_text(row.get("city"))
        key = neighborhood_key(name, city)
        group = groups.get(key)
        if group is None:
            group = groups[key] = _Group(name=name, city=city)
        group.count += 1
        if row.get("messageable"):
            group.messageable += 1
        if row.get("support_level") == SupportLevel.APOIADOR:
            group.supporters += 1
        group.members[row.get("registered_by_id")] += 1

        lat, lng = row.get("latitude"), row.get("longitude")
        if valid_coordinates(lat, lng):
            lat, lng = float(lat), float(lng)
            group.mapped += 1
            group.lat_sum += lat
            group.lng_sum += lng
            if row.get("geo_status") == GeoStatus.APPROXIMATE:
                approximate += 1
            min_lat, max_lat = min(min_lat, lat), max(max_lat, lat)
            min_lng, max_lng = min(min_lng, lng), max(max_lng, lng)
            geocoded.append((row.get("id"), lat, lng))

    neighborhoods: list[dict] = []
    without_geo: list[dict] = []
    for key, g in groups.items():
        base = {
            "key": key,
            "name": g.name or UNKNOWN_NEIGHBORHOOD,
            "known": bool(g.name),
            "city": g.city,
            "count": g.count,
        }
        if g.mapped == 0:
            without_geo.append(base)
            continue
        members = sorted(
            ({"name": member_names.get(member_id) or UNKNOWN_MEMBER, "count": n} for member_id, n in g.members.items()),
            key=lambda m: (-m["count"], normalize_text(m["name"]), m["name"]),
        )[:top_members]
        neighborhoods.append(
            {
                **base,
                "mapped": g.mapped,
                "lat": round(g.lat_sum / g.mapped, 6),
                "lng": round(g.lng_sum / g.mapped, 6),
                "messageable": g.messageable,
                "supporters": g.supporters,
                "top_members": members,
            }
        )
    neighborhoods.sort(key=_by_count_then_name)
    without_geo.sort(key=_by_count_then_name)

    with_geo = len(geocoded)
    bounds = (
        [[round(min_lat, 6), round(min_lng, 6)], [round(max_lat, 6), round(max_lng, 6)]] if with_geo else None
    )
    points = [{"id": str(pid), "lat": round(lat, 5), "lng": round(lng, 5)} for pid, lat, lng in sample_points(geocoded, limit)]

    return {
        "totals": {"voters": total, "with_geo": with_geo, "without_geo": total - with_geo, "approximate": approximate},
        "neighborhoods": neighborhoods,
        "neighborhoods_without_geo": without_geo,
        "points": points,
        "truncated": with_geo > limit,
        "bounds": bounds,
        "can_view_voters": bool(can_view_voters),
    }


def decorate_with_scale(data: dict) -> dict:
    """Acrescenta cor e raio de cada bairro e a legenda (a escala é calculada no servidor: uma só fonte de verdade)."""
    max_count = max((n["count"] for n in data["neighborhoods"]), default=0)
    bins = build_color_scale(max_count)
    for n in data["neighborhoods"]:
        n["color"] = color_for_count(n["count"], bins)
        n["radius"] = radius_for_count(n["count"], max_count)
    data["legend"] = {"max_count": max_count, "bins": [b.as_dict() for b in bins]}
    return data


def build_map_payload(
    rows: Iterable[Mapping[str, Any]],
    *,
    member_names: Mapping[Any, str],
    can_view_voters: bool,
    point_limit: int | None = None,
    top_members: int = TOP_MEMBERS_PER_NEIGHBORHOOD,
) -> dict:
    """Resposta completa do endpoint: agregação + escala visual."""
    return decorate_with_scale(
        aggregate_map_data(
            rows,
            member_names=member_names,
            can_view_voters=can_view_voters,
            point_limit=point_limit,
            top_members=top_members,
        )
    )
