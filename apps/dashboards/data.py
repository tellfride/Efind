"""Cálculo dos dados dos widgets.

TODA consulta de eleitores passa por `apps.core.access.voters_queryset(user, filtros)` e a de equipe por `team_scope(user)`,
portanto respeita a campanha e o escopo hierárquico de quem está vendo (ADMIN: tudo; COORDENADOR: sua rede; CABO: só ele).
O resultado de `compute_widget_data` é sempre um dict serializável em JSON (ids como texto, datas em ISO).
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from django.db.models import Count, DateTimeField, ExpressionWrapper, F, Max, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.core.access import MESSAGEABLE_Q, SAO_PAULO, team_scope, voters_queryset
from apps.core.constants import (
    BroadcastStatus,
    Gender,
    Role,
    SupportLevel,
    VoterSource,
)
from apps.core.permissions import can

from . import aggregate as agg
from .widgets import WIDGET_CATALOG, effective_limit, effective_period, widget_data_key

logger = logging.getLogger(__name__)

MAX_RANKING_ROWS = 500
MAX_TEAM_ROWS = 2000
ERROR_MESSAGE = "Não foi possível carregar este widget."


class DataContext:
    """Cache por requisição: evita refazer escopo, equipe e permissões para cada widget do dashboard."""

    def __init__(self, user, perms=None, now: dt.datetime | None = None):
        self.user = user
        self.now = now or timezone.now()
        self._perms = perms
        self._voters: dict[str, Any] = {}
        self._team: list[agg.TeamMember] | None = None
        self._goal: tuple[int | None] | None = None

    @property
    def perms(self):
        if self._perms is None:
            from apps.accounts.services import permissions_for

            self._perms = permissions_for(self.user)
        return self._perms

    def voters(self, filters: dict | None = None):
        """Eleitores do escopo do usuário AND filtros do widget (queryset preguiçoso, reaproveitado por filtros iguais)."""
        key = repr(sorted((filters or {}).items()))
        if key not in self._voters:
            self._voters[key] = voters_queryset(self.user, filters)
        return self._voters[key].order_by()

    def team(self) -> list[agg.TeamMember]:
        if self._team is None:
            users = team_scope(self.user).select_related("parent").order_by("name")[:MAX_TEAM_ROWS]
            self._team = [
                agg.TeamMember(
                    id=str(u.pk),
                    name=u.name,
                    role=u.role,
                    active=u.is_active,
                    goal=u.goal,
                    parent_id=str(u.parent_id) if u.parent_id else None,
                    parent_name=u.parent.name if u.parent_id else None,
                    parent_role=u.parent.role if u.parent_id else None,
                )
                for u in users
            ]
        return self._team

    def campaign_goal(self) -> int | None:
        if self._goal is None:
            from apps.campaigns.models import Campaign

            goal = Campaign.objects.filter(pk=self.user.campaign_id).values_list("voter_goal", flat=True).first()
            self._goal = (goal,)
        return self._goal[0]


# ---------------------------------------------------------------------------------------------
# Consultas auxiliares
# ---------------------------------------------------------------------------------------------


def _filters(widget: dict) -> dict:
    return (widget.get("config") or {}).get("filters") or {}


def _day_counts(qs, start: dt.datetime, now: dt.datetime) -> dict[str, int]:
    """Cadastros por dia de São Paulo desde `start`, agrupados no banco.

    Não usa CONVERT_TZ (exigiria as tabelas de fuso do MariaDB): desloca `created_at` pelo deslocamento de São Paulo
    (UTC−3, sem horário de verão desde 2019) e extrai a data em UTC.
    """
    offset = now.astimezone(SAO_PAULO).utcoffset() or dt.timedelta(0)
    local = ExpressionWrapper(F("created_at") + offset, output_field=DateTimeField())
    rows = (
        qs.filter(created_at__gte=start)
        .annotate(day=TruncDate(local, tzinfo=dt.timezone.utc))
        .order_by()
        .values("day")
        .annotate(n=Count("id"))
    )
    return {r["day"].isoformat(): r["n"] for r in rows if r["day"] is not None}


def _registrant_stats(qs, start: dt.datetime) -> agg.RegistrantStats:
    rows = qs.values("registered_by_id").annotate(
        total=Count("id"),
        in_period=Count("id", filter=Q(created_at__gte=start)),
        last=Max("created_at"),
    )
    total, in_period, last = {}, {}, {}
    for r in rows:
        key = str(r["registered_by_id"])
        total[key] = r["total"]
        in_period[key] = r["in_period"]
        last[key] = r["last"]
    return agg.RegistrantStats(total=total, in_period=in_period, last_at=last)


def _group_counts(qs, field: str) -> list[tuple[str | None, int]]:
    return [(r[field], r["n"]) for r in qs.values(field).annotate(n=Count("id")).order_by()]


# ---------------------------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------------------------


def _kpi_total(ctx: DataContext, widget: dict) -> dict:
    last7 = agg.period_range(7, ctx.now).start
    res = ctx.voters(_filters(widget)).aggregate(total=Count("id"), last7=Count("id", filter=Q(created_at__gte=last7)))
    return {"type": "kpi_total", "total": res["total"], "last7": res["last7"]}


def _kpi_today(ctx: DataContext, widget: dict) -> dict:
    today, yesterday = agg.today_range(ctx.now)
    res = ctx.voters(_filters(widget)).aggregate(
        today=Count("id", filter=Q(created_at__gte=today)),
        yesterday=Count("id", filter=Q(created_at__gte=yesterday, created_at__lt=today)),
    )
    return {"type": "kpi_today", "today": res["today"], "yesterday": res["yesterday"]}


def _kpi_period(ctx: DataContext, widget: dict) -> dict:
    period = effective_period(widget)
    rng = agg.period_range(period, ctx.now)
    res = ctx.voters(_filters(widget)).aggregate(
        current=Count("id", filter=Q(created_at__gte=rng.start)),
        previous=Count("id", filter=Q(created_at__gte=rng.previous_start, created_at__lt=rng.start)),
    )
    return {"type": "kpi_period", "period": period, "comparison": agg.compare_periods(res["current"], res["previous"])}


def _kpi_goal(ctx: DataContext, widget: dict) -> dict:
    total = ctx.voters(_filters(widget)).count()
    team_goal, members = agg.team_goal_sum(ctx.team())
    if ctx.user.role == Role.ADMIN:
        goal = ctx.campaign_goal()
        source = "campaign"
    else:
        goal = team_goal or None
        source = "team"
    return {
        "type": "kpi_goal",
        "total": total,
        "goal": goal,
        "pct": agg.percent(total, goal),
        "source": source,
        "members_with_goal": members,
    }


def _kpi_messageable(ctx: DataContext, widget: dict) -> dict:
    res = ctx.voters(_filters(widget)).aggregate(total=Count("id"), messageable=Count("id", filter=MESSAGEABLE_Q))
    return {
        "type": "kpi_messageable",
        "messageable": res["messageable"],
        "total": res["total"],
        "pct": agg.percent(res["messageable"], res["total"]),
    }


def _kpi_team(ctx: DataContext, widget: dict) -> dict:
    period = effective_period(widget)
    start = agg.period_range(period, ctx.now).start
    filters = _filters(widget)
    members = [m for m in agg.filter_members_by_voter_filters(ctx.team(), filters) if m.active]
    active_ids = {m.id for m in members}
    registrants = (
        ctx.voters(filters).filter(created_at__gte=start).values_list("registered_by_id", flat=True).distinct()
    )
    contributing = len({str(r) for r in registrants} & active_ids)
    return {
        "type": "kpi_team",
        "period": period,
        "active": len(members),
        "contributing": contributing,
        "pct": agg.percent(contributing, len(members)),
    }


def _ranking_members(ctx: DataContext, widget: dict) -> dict:
    period = effective_period(widget)
    filters = _filters(widget)
    start = agg.period_range(period, ctx.now).start
    stats = _registrant_stats(ctx.voters(filters), start)
    rows = agg.compute_member_ranking(agg.filter_members_by_voter_filters(ctx.team(), filters), stats)
    return {
        "type": "ranking_members",
        "period": period,
        "rows": rows[:MAX_RANKING_ROWS],
        "total": sum(stats.total.values()),
        "period_total": sum(stats.in_period.values()),
        "contributing": sum(1 for v in stats.in_period.values() if v > 0),
        "active_members": sum(1 for r in rows if r["active"]),
        "limit": effective_limit(widget),
    }


def _ranking_coordinators(ctx: DataContext, widget: dict) -> dict:
    period = effective_period(widget)
    limit = effective_limit(widget)
    if ctx.user.role == Role.CABO:
        return {"type": "ranking_coordinators", "period": period, "applicable": False, "rows": [], "others": None, "limit": limit}
    filters = _filters(widget)
    start = agg.period_range(period, ctx.now).start
    stats = _registrant_stats(ctx.voters(filters), start)
    result = agg.compute_coordinator_ranking(ctx.team(), stats)
    rows, others = result["rows"], result["others"]
    if coordinator_ids := filters.get("coordinator_ids"):
        rows = [r for r in rows if r["id"] in set(coordinator_ids)]
        others = None
    return {
        "type": "ranking_coordinators",
        "period": period,
        "applicable": True,
        "rows": rows[:200],
        "others": others,
        "limit": limit,
    }


def _timeline(ctx: DataContext, widget: dict) -> dict:
    period = effective_period(widget)
    rng = agg.period_range(period, ctx.now)
    qs = ctx.voters(_filters(widget))
    counts = _day_counts(qs, rng.start, ctx.now)
    previous_total = qs.filter(created_at__gte=rng.previous_start, created_at__lt=rng.start).count()
    points = agg.fill_timeline(counts, rng.start_key, rng.end_key)
    return {
        "type": "timeline",
        "period": period,
        "points": points,
        "total": sum(p["count"] for p in points),
        "previous_total": previous_total,
    }


def _top_list(field: str, type_: str):
    def compute(ctx: DataContext, widget: dict) -> dict:
        rows = _group_counts(ctx.voters(_filters(widget)), field)
        return {"type": type_, **agg.top_n(rows, effective_limit(widget))}

    return compute


def _distribution(field: str, type_: str, choices, unknown_label: str = "Não informado"):
    order = [value for value, _ in choices.choices]
    labels = dict(choices.choices)

    def compute(ctx: DataContext, widget: dict) -> dict:
        rows = _group_counts(ctx.voters(_filters(widget)), field)
        return {"type": type_, **agg.to_distribution(rows, order, labels, unknown_label)}

    return compute


def _by_age(ctx: DataContext, widget: dict) -> dict:
    today = agg.sao_paulo_today(ctx.now)
    aggregates: dict[str, Any] = {}
    for bucket in agg.AGE_BUCKETS:
        lte, gt = agg.birth_date_bounds(bucket["min"], bucket["max"], today)
        cond = Q(birth_date__lte=lte)
        if gt is not None:
            cond &= Q(birth_date__gt=gt)
        aggregates[bucket["key"]] = Count("id", filter=cond)
    youngest_ok = agg.birth_date_bounds(agg.AGE_MIN, None, today)[0]
    aggregates[agg.AGE_UNKNOWN["key"]] = Count("id", filter=Q(birth_date__isnull=True) | Q(birth_date__gt=youngest_ok))
    counts = ctx.voters(_filters(widget)).aggregate(**{f"b_{k}": v for k, v in aggregates.items()})
    rows = [
        {"key": b["key"], "label": b["label"], "count": counts[f"b_{b['key']}"]}
        for b in (*agg.AGE_BUCKETS, agg.AGE_UNKNOWN)
    ]
    return {"type": "by_age", "rows": rows, "total": sum(r["count"] for r in rows)}


def _recent_voters(ctx: DataContext, widget: dict) -> dict:
    if not can(ctx.perms, "eleitores", "view"):
        return {"type": "recent_voters", "locked": True, "rows": []}
    rows = (
        ctx.voters(_filters(widget))
        .order_by("-created_at")
        .values("id", "name", "neighborhood", "city", "created_at", "registered_by__name")[: effective_limit(widget)]
    )
    return {
        "type": "recent_voters",
        "locked": False,
        "rows": [
            {
                "id": str(r["id"]),
                "name": r["name"],
                "neighborhood": r["neighborhood"] or None,
                "city": r["city"] or None,
                "registered_by": r["registered_by__name"],
                "created_at": r["created_at"].isoformat(),
                "url": f"/painel/eleitores/{r['id']}/",
            }
            for r in rows
        ],
    }


def _broadcasts(ctx: DataContext, widget: dict) -> dict:
    from apps.messaging.models import Broadcast, BroadcastMessage

    user = ctx.user
    period = effective_period(widget)
    is_admin = user.role == Role.ADMIN
    scope = "campaign" if is_admin else "own"
    empty = {"sent": 0, "delivered": 0, "read": 0, "failed": 0, "pending": 0, "delivery_rate": None, "read_rate": None, "recent": []}
    if not can(ctx.perms, "disparos", "view"):
        return {"type": "broadcasts", "locked": True, "period": period, "scope": scope, **empty}

    start = agg.period_range(period, ctx.now).start
    broadcasts = Broadcast.objects.filter(campaign_id=user.campaign_id)
    messages = BroadcastMessage.objects.filter(campaign_id=user.campaign_id, created_at__gte=start)
    if not is_admin:  # quem não é administrador só enxerga os disparos que criou
        broadcasts = broadcasts.filter(created_by_id=user.pk)
        messages = messages.filter(broadcast__created_by_id=user.pk)
    counts = {r["status"]: r["n"] for r in messages.order_by().values("status").annotate(n=Count("id"))}
    valid_status = {c.value for c in BroadcastStatus}
    recent = broadcasts.order_by("-created_at").values(
        "id", "name", "status", "total_recipients", "sent_count", "delivered_count", "read_count", "failed_count", "created_at"
    )[:5]
    return {
        "type": "broadcasts",
        "locked": False,
        "period": period,
        "scope": scope,
        **agg.broadcast_rates(counts),
        "recent": [
            {
                "id": str(b["id"]),
                "name": b["name"],
                "status": b["status"] if b["status"] in valid_status else BroadcastStatus.DRAFT.value,
                "status_label": BroadcastStatus(b["status"]).label if b["status"] in valid_status else "Rascunho",
                "total_recipients": b["total_recipients"],
                "sent_count": b["sent_count"],
                "delivered_count": b["delivered_count"],
                "read_count": b["read_count"],
                "failed_count": b["failed_count"],
                "created_at": b["created_at"].isoformat(),
            }
            for b in recent
        ],
    }


def _goals_progress(ctx: DataContext, widget: dict) -> dict:
    filters = _filters(widget)
    totals = {
        str(r["registered_by_id"]): r["n"]
        for r in ctx.voters(filters).values("registered_by_id").annotate(n=Count("id")).order_by()
    }
    result = agg.compute_goals_progress(agg.filter_members_by_voter_filters(ctx.team(), filters), totals)
    return {"type": "goals_progress", "rows": result["rows"][: effective_limit(widget)], "without_goal": result["without_goal"]}


def _note(ctx: DataContext, widget: dict) -> dict:
    return {"type": "note"}


_COMPUTE = {
    "kpi_total": _kpi_total,
    "kpi_today": _kpi_today,
    "kpi_period": _kpi_period,
    "kpi_goal": _kpi_goal,
    "kpi_messageable": _kpi_messageable,
    "kpi_team": _kpi_team,
    "ranking_members": _ranking_members,
    "ranking_coordinators": _ranking_coordinators,
    "timeline": _timeline,
    "by_neighborhood": _top_list("neighborhood", "by_neighborhood"),
    "by_city": _top_list("city", "by_city"),
    "by_gender": _distribution("gender", "by_gender", Gender),
    "by_support": _distribution("support_level", "by_support", SupportLevel, "Sem classificação"),
    "by_source": _distribution("source", "by_source", VoterSource),
    "by_age": _by_age,
    "recent_voters": _recent_voters,
    "broadcasts": _broadcasts,
    "goals_progress": _goals_progress,
    "note": _note,
}
assert set(_COMPUTE) == set(WIDGET_CATALOG), "todo tipo do catálogo precisa de um cálculo"


def compute_widget_data(user, widget: dict, ctx: DataContext | None = None) -> dict:
    """Dados de UM widget dentro do escopo do usuário (o widget já deve ter passado por `validate_widgets`)."""
    ctx = ctx or DataContext(user)
    compute = _COMPUTE.get(widget.get("type"))
    if compute is None:
        raise ValueError("Tipo de widget desconhecido.")
    return compute(ctx, widget)


def compute_dashboard_data(user, widgets: list[dict], perms=None, now: dt.datetime | None = None) -> dict[str, dict]:
    """Dados de vários widgets: {id: dados | {"error": "..."}}. Widgets com os mesmos dados são calculados uma vez só.

    Falha de um widget não derruba os demais; o log registra só o tipo e a classe do erro (sem dados pessoais).
    """
    ctx = DataContext(user, perms=perms, now=now)
    by_key: dict[str, dict] = {}
    result: dict[str, dict] = {}
    for widget in widgets:
        key = widget_data_key(widget)
        if key not in by_key:
            try:
                by_key[key] = compute_widget_data(user, widget, ctx)
            except Exception as exc:  # noqa: BLE001 — um widget com problema não pode quebrar o painel
                logger.warning("Falha ao calcular widget %s: %s", widget.get("type"), exc.__class__.__name__)
                by_key[key] = {"error": ERROR_MESSAGE}
        result[widget["id"]] = by_key[key]
    return result
