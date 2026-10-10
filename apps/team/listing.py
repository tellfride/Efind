"""Tela de equipe: linhas com contagens, árvore hierárquica, filtros, ordenação e resumo.

A parte pura (dataclasses, `build_tree`, `filter_rows`, `sort_rows`, `summarize`) não toca o banco.
`load_team_rows(user)` faz 2 consultas no total (membros do escopo + UMA agregação de eleitores), sem N+1.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from typing import Any

from django.db.models import Count, Q
from django.utils import timezone

from apps.core.access import team_scope, voter_scope
from apps.core.constants import Role, label_of
from apps.core.utils import normalize_text

from .rules import goal_percent, goal_tone

ROLE_ORDER = {Role.ADMIN.value: 0, Role.COORDENADOR.value: 1, Role.CABO.value: 2}
ROLE_TONES = {Role.ADMIN.value: "purple", Role.COORDENADOR.value: "blue", Role.CABO.value: "gray"}
STATUS_CHOICES = (("", "Todos os status"), ("ativos", "Somente ativos"), ("inativos", "Somente inativos"))
SORT_CHOICES = (
    ("eleitores", "Mais eleitores"),
    ("menos", "Menos eleitores"),
    ("7d", "Mais cadastros em 7 dias"),
    ("meta", "Maior % da meta"),
    ("nome", "Nome (A–Z)"),
)
DEFAULT_SORT = "eleitores"


@dataclass
class MemberRow:
    """Um membro da equipe com as contagens de eleitores cadastrados por ele."""

    id: uuid.UUID
    name: str
    email: str
    phone: str
    role: str
    parent_id: uuid.UUID | None
    parent_name: str
    is_active: bool
    goal: int | None
    region: str
    last_login: dt.datetime | None
    voters_total: int = 0
    voters_7d: int = 0
    is_self: bool = False

    @property
    def role_label(self) -> str:
        return label_of(Role, self.role)

    @property
    def role_tone(self) -> str:
        return ROLE_TONES.get(self.role, "gray")

    @property
    def goal_percent(self) -> float | None:
        return goal_percent(self.voters_total, self.goal)

    @property
    def goal_tone(self) -> str:
        return goal_tone(self.goal_percent)

    @property
    def sort_name(self) -> str:
        return normalize_text(self.name)


@dataclass
class TreeNode:
    row: MemberRow
    children: list[TreeNode] = field(default_factory=list)
    network_total: int = 0  # eleitores do membro + de toda a rede abaixo dele
    size: int = 1  # membros na subárvore (incluindo ele)

    @property
    def has_children(self) -> bool:
        return bool(self.children)


@dataclass
class ListFilters:
    q: str = ""
    role: str = ""
    coordinator: str = ""
    status: str = ""
    sort: str = DEFAULT_SORT

    @property
    def active_count(self) -> int:
        return sum(1 for v in (self.q, self.role, self.coordinator, self.status) if v)


@dataclass
class TeamSummary:
    total: int = 0
    admins: int = 0
    coordinators: int = 0
    cabos: int = 0
    active: int = 0
    inactive: int = 0
    voters: int = 0
    voters_7d: int = 0
    idle_7d: int = 0  # coordenadores e cabos ativos sem cadastros nos últimos 7 dias


# --------------------------------------------------------------------------------------------
# Carga (2 consultas)
# --------------------------------------------------------------------------------------------


def load_team_rows(user, *, now: dt.datetime | None = None) -> list[MemberRow]:
    """Membros visíveis ao usuário + contagens de eleitores (total e últimos 7 dias).

    Consulta 1: membros do escopo (`team_scope`). Consulta 2: UMA agregação sobre `voter_scope(user)`
    agrupada por `registered_by` — o escopo/campanha do usuário já limitam as linhas.
    """
    now = now or timezone.now()
    since = now - dt.timedelta(days=7)
    members = list(team_scope(user).select_related("parent"))
    counts = {
        r["registered_by_id"]: r
        for r in voter_scope(user)
        .order_by()
        .values("registered_by_id")
        .annotate(total=Count("id"), recent=Count("id", filter=Q(created_at__gte=since)))
    }
    rows = []
    for m in members:
        c = counts.get(m.id)
        rows.append(
            MemberRow(
                id=m.id,
                name=m.name,
                email=m.email,
                phone=m.phone,
                role=m.role,
                parent_id=m.parent_id,
                parent_name=m.parent.name if m.parent_id and m.parent else "",
                is_active=m.is_active,
                goal=m.goal,
                region=m.region,
                last_login=m.last_login,
                voters_total=c["total"] if c else 0,
                voters_7d=c["recent"] if c else 0,
                is_self=m.id == user.id,
            )
        )
    return rows


# --------------------------------------------------------------------------------------------
# Árvore
# --------------------------------------------------------------------------------------------


def compare_key(row: MemberRow) -> tuple:
    """Ordem padrão: papel (admin → coordenador → cabo), ativos antes, nome."""
    return (ROLE_ORDER.get(row.role, 9), 0 if row.is_active else 1, row.sort_name)


def build_tree(rows: list[MemberRow]) -> list[TreeNode]:
    """Monta a árvore admin → coordenadores → cabos com os membros visíveis. Quem não tem o superior entre os
    visíveis vira raiz (ex.: o próprio coordenador na visão dele). Protegido contra ciclos."""
    by_id = {r.id: r for r in rows}
    children_of: dict[Any, list[MemberRow]] = {}
    roots: list[MemberRow] = []
    for r in rows:
        if r.parent_id and r.parent_id != r.id and r.parent_id in by_id:
            children_of.setdefault(r.parent_id, []).append(r)
        else:
            roots.append(r)

    visited: set[Any] = set()

    def build(r: MemberRow) -> TreeNode:
        visited.add(r.id)
        kids = [build(k) for k in sorted(children_of.get(r.id, []), key=compare_key) if k.id not in visited]
        return TreeNode(
            row=r,
            children=kids,
            network_total=r.voters_total + sum(k.network_total for k in kids),
            size=1 + sum(k.size for k in kids),
        )

    tree = [build(r) for r in sorted(roots, key=compare_key)]
    for r in sorted(rows, key=compare_key):  # presos em ciclo (dados inconsistentes) entram como raízes
        if r.id not in visited:
            tree.append(build(r))
    return tree


# --------------------------------------------------------------------------------------------
# Filtros e ordenação (lista)
# --------------------------------------------------------------------------------------------


def parse_list_filters(params, valid_coordinator_ids: set[str] | None = None) -> ListFilters:
    """Lê e valida os parâmetros da URL (`q`, `papel`, `coord`, `status`, `ordem`)."""
    role = params.get("papel", "")
    coordinator = params.get("coord", "")
    status = params.get("status", "")
    sort = params.get("ordem", "")
    return ListFilters(
        q=(params.get("q", "") or "").strip()[:100],
        role=role if role in (Role.ADMIN, Role.COORDENADOR, Role.CABO) else "",
        coordinator=coordinator if valid_coordinator_ids is None or coordinator in valid_coordinator_ids else "",
        status=status if status in ("ativos", "inativos") else "",
        sort=sort if sort in dict(SORT_CHOICES) else DEFAULT_SORT,
    )


def filter_rows(rows: list[MemberRow], f: ListFilters) -> list[MemberRow]:
    q = normalize_text(f.q)
    digits = "".join(c for c in f.q if c.isdigit())
    out = []
    for r in rows:
        if f.role and r.role != f.role:
            continue
        if f.status == "ativos" and not r.is_active:
            continue
        if f.status == "inativos" and r.is_active:
            continue
        if f.coordinator and str(r.id) != f.coordinator and str(r.parent_id) != f.coordinator:
            continue
        if q:
            text = normalize_text(f"{r.name} {r.email} {r.region}")
            phone_match = len(digits) >= 4 and digits in "".join(c for c in r.phone if c.isdigit())
            if q not in text and not phone_match:
                continue
        out.append(r)
    return out


def sort_rows(rows: list[MemberRow], sort: str = DEFAULT_SORT) -> list[MemberRow]:
    if sort == "nome":
        return sorted(rows, key=lambda r: r.sort_name)
    if sort == "menos":
        return sorted(rows, key=lambda r: (r.voters_total, r.sort_name))
    if sort == "7d":
        return sorted(rows, key=lambda r: (-r.voters_7d, -r.voters_total, r.sort_name))
    if sort == "meta":
        # sem meta vai para o fim
        return sorted(
            rows,
            key=lambda r: (r.goal_percent is None, -(r.goal_percent or 0), r.sort_name),
        )
    return sorted(rows, key=lambda r: (-r.voters_total, r.sort_name))


def summarize(rows: list[MemberRow]) -> TeamSummary:
    s = TeamSummary()
    for r in rows:
        s.total += 1
        if r.role == Role.ADMIN:
            s.admins += 1
        elif r.role == Role.COORDENADOR:
            s.coordinators += 1
        else:
            s.cabos += 1
        if r.is_active:
            s.active += 1
        else:
            s.inactive += 1
        s.voters += r.voters_total
        s.voters_7d += r.voters_7d
        if r.is_active and r.role != Role.ADMIN and r.voters_7d == 0:
            s.idle_7d += 1
    return s


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def roles_hint(s: TeamSummary) -> str:
    """"1 administrador · 2 coordenadores · 8 cabos" (omite papéis sem membros)."""
    parts = []
    if s.admins:
        parts.append(_plural(s.admins, "administrador", "administradores"))
    if s.coordinators:
        parts.append(_plural(s.coordinators, "coordenador", "coordenadores"))
    if s.cabos:
        parts.append(_plural(s.cabos, "cabo", "cabos"))
    return " · ".join(parts)
