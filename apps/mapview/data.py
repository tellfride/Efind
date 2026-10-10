"""Leitura dos dados do mapa, sempre dentro da campanha e do escopo hierárquico do usuário.

A consulta parte de `voters_queryset(user, filtros)` (escopo AND filtros); a agregação é feita pelas funções
puras de `aggregate.py`, alimentadas por linhas `values_list()` mínimas (sem nome, telefone ou e-mail).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from django.db.models import BooleanField, Case, Count, Value, When

from apps.core.access import MESSAGEABLE_Q, team_scope, voter_scope, voters_queryset
from apps.core.constants import GeoStatus

from .aggregate import build_map_payload

# Colunas lidas do banco (nenhuma é dado pessoal além da localização aproximada)
ROW_FIELDS = (
    "id",
    "latitude",
    "longitude",
    "geo_status",
    "neighborhood",
    "city",
    "support_level",
    "messageable",
    "registered_by_id",
)


def map_filters(filters: Mapping[str, Any] | None) -> dict:
    """Filtros aplicáveis ao mapa: "Localização no mapa" (has_geo) não faz sentido aqui, pois o mapa mostra
    quem tem e quem não tem coordenadas."""
    return {key: value for key, value in (filters or {}).items() if key != "has_geo"}


def map_voters(user, filters: Mapping[str, Any] | None = None):
    """Eleitores do mapa = escopo do usuário AND filtros (sem has_geo)."""
    return voters_queryset(user, map_filters(filters))


def iter_map_rows(user, filters: Mapping[str, Any] | None = None) -> Iterator[dict]:
    """Linhas mínimas dos eleitores visíveis, uma de cada vez (evita guardar dicionários de todos os eleitores)."""
    queryset = (
        map_voters(user, filters)
        .annotate(
            # Mesmo critério de MESSAGEABLE_Q: consentiu, optou pelo WhatsApp e não pediu descadastro
            messageable=Case(When(MESSAGEABLE_Q, then=Value(True)), default=Value(False), output_field=BooleanField())
        )
        .order_by("created_at", "id")
        .values_list(*ROW_FIELDS)
    )
    for values in queryset.iterator(chunk_size=2000):
        yield dict(zip(ROW_FIELDS, values))


def load_map_data(user, filters: Mapping[str, Any] | None = None, *, can_view_voters: bool = False) -> dict:
    """Dados agregados do mapa para os filtros informados, no escopo do usuário."""
    # Quem cadastrou sempre está no escopo de equipe do usuário (mesma regra de voter_scope)
    member_names = dict(team_scope(user).values_list("id", "name"))
    return build_map_payload(iter_map_rows(user, filters), member_names=member_names, can_view_voters=can_view_voters)


def geo_queue_counts(user) -> dict[str, int]:
    """Eleitores da campanha aguardando (PENDING) ou que falharam (FAILED) na geocodificação.

    Usado só pelo ADMIN (cujo escopo é a campanha inteira); mesmo assim parte de `voter_scope`.
    """
    rows = (
        voter_scope(user)
        .filter(geo_status__in=(GeoStatus.PENDING, GeoStatus.FAILED))
        .order_by()
        .values("geo_status")
        .annotate(n=Count("id"))
    )
    by_status = {row["geo_status"]: row["n"] for row in rows}
    pending = by_status.get(GeoStatus.PENDING, 0)
    failed = by_status.get(GeoStatus.FAILED, 0)
    return {"pending": pending, "failed": failed, "total": pending + failed}
