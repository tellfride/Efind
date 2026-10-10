"""Opções do painel de filtros de eleitores (bairros, cidades, equipe, tags...), sempre dentro do escopo do usuário,
e montagem dos campos do painel `{% voter_filters %}`."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from django.db.models import Count

from .access import team_scope, voter_scope
from .constants import Gender, Role, SupportLevel, VoterSource
from .utils import parse_tags
from .voter_filters import URL_PARAMS, count_active_filters

ROLE_HINT = {Role.ADMIN: "Administrador", Role.COORDENADOR: "Coordenador", Role.CABO: "Cabo eleitoral"}


def _opt(value, label=None, count=None, hint="") -> dict:
    return {"value": str(value), "label": label if label is not None else str(value), "count": count, "hint": hint}


def get_voter_filter_options(user) -> dict[str, list[dict]]:
    """Opções (value/label/count/hint) para cada filtro multi-seleção, calculadas no escopo do usuário."""
    scope = voter_scope(user)

    by_hood: dict[str, dict[str, Any]] = {}
    rows = scope.exclude(neighborhood="").values("neighborhood", "city").annotate(n=Count("id"))
    for r in rows:
        entry = by_hood.setdefault(r["neighborhood"], {"count": 0, "cities": set()})
        entry["count"] += r["n"]
        if r["city"]:
            entry["cities"].add(r["city"])
    neighborhoods = [
        _opt(name, count=e["count"], hint=", ".join(sorted(e["cities"])))
        for name, e in sorted(by_hood.items(), key=lambda kv: kv[0].lower())
    ]

    cities = [
        _opt(r["city"], count=r["n"])
        for r in scope.exclude(city="").values("city").annotate(n=Count("id")).order_by("city")
    ]
    zones = [
        _opt(r["electoral_zone"], f"Zona {r['electoral_zone']}", r["n"])
        for r in scope.exclude(electoral_zone="").values("electoral_zone").annotate(n=Count("id")).order_by("electoral_zone")
    ]

    tag_count: Counter[str] = Counter()
    for stored in scope.exclude(tags="").values_list("tags", flat=True)[:20000]:
        tag_count.update(parse_tags(stored))
    tags = [_opt(t, count=c) for t, c in tag_count.most_common()]

    team = list(team_scope(user).values("id", "name", "role", "is_active").order_by("name"))
    members = [
        _opt(m["id"], m["name"], hint=f"{ROLE_HINT.get(m['role'], m['role'])}{'' if m['is_active'] else ' · inativo'}")
        for m in team
    ]
    coordinators = (
        [_opt(m["id"], m["name"], hint="" if m["is_active"] else "inativo") for m in team if m["role"] == Role.COORDENADOR]
        if user.role == Role.ADMIN
        else []
    )
    return {
        "neighborhoods": neighborhoods,
        "cities": cities,
        "coordinators": coordinators,
        "members": members,
        "tags": tags,
        "electoral_zones": zones,
    }


ALL_FIELDS = (
    "q",
    "neighborhoods",
    "cities",
    "coordinator_ids",
    "registered_by_ids",
    "support_levels",
    "genders",
    "age",
    "tags",
    "sources",
    "electoral_zones",
    "created",
    "has_geo",
    "messageable",
)
PRIMARY_FIELDS = ("q", "neighborhoods", "cities", "registered_by_ids")

_ENUM_OPTIONS = {
    "genders": [_opt(v, l) for v, l in Gender.choices],
    "support_levels": [_opt(v, l) for v, l in SupportLevel.choices],
    "sources": [_opt(v, l) for v, l in VoterSource.choices],
}

# campo → (rótulo, chave em options, placeholder)
_MULTI = {
    "neighborhoods": ("Bairros", "neighborhoods", "Todos os bairros"),
    "cities": ("Cidades", "cities", "Todas as cidades"),
    "coordinator_ids": ("Coordenadores", "coordinators", "Todos"),
    "registered_by_ids": ("Cadastrado por", "members", "Toda a equipe"),
    "support_levels": ("Nível de apoio", None, "Todos"),
    "genders": ("Gênero", None, "Todos"),
    "tags": ("Tags", "tags", "Qualquer tag"),
    "sources": ("Origem do cadastro", None, "Todas"),
    "electoral_zones": ("Zona eleitoral", "electoral_zones", "Todas"),
}


def build_filter_panel(filters: dict, options: dict, fields=None, hide=(), expanded=False) -> dict:
    """Dados para components/voter_filters.html."""
    wanted = [f for f in (fields or ALL_FIELDS) if f not in hide]
    multi, singles = [], {}
    for key in wanted:
        if key in _MULTI:
            label, opt_key, placeholder = _MULTI[key]
            opts = options.get(opt_key, []) if opt_key else _ENUM_OPTIONS[key]
            # Oculta filtros sem opções úteis (ex.: coordenadores para quem não é admin; 1 só membro)
            if opt_key in ("coordinators", "tags", "electoral_zones") and not opts:
                continue
            if key == "registered_by_ids" and len(opts) <= 1:
                continue
            cfg = {
                "name": URL_PARAMS[key],
                "options": opts,
                "selected": filters.get(key, []),
                "placeholder": placeholder,
            }
            multi.append({"key": key, "label": label, "primary": key in PRIMARY_FIELDS, "json": json.dumps(cfg, ensure_ascii=False)})
        else:
            singles[key] = True
    has_secondary = any(not m["primary"] for m in multi) or any(k not in ("q",) for k in singles)
    return {
        "multi": multi,
        "singles": singles,
        "has_secondary": has_secondary,
        "active_count": count_active_filters(filters),
        "expanded": expanded or any(not m["primary"] and filters.get(m["key"]) for m in multi),
    }
