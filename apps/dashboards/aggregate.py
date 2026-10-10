"""Funções puras de agregação dos widgets (sem banco) — fáceis de testar.

Dias sempre no fuso America/Sao_Paulo. Chaves de dia = "AAAA-MM-DD".
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from apps.core.access import SAO_PAULO
from apps.core.constants import Role
from apps.core.utils import normalize_text

# ---------------------------------------------------------------------------------------------
# Datas e períodos
# ---------------------------------------------------------------------------------------------


def sao_paulo_today(now: dt.datetime | None = None) -> dt.date:
    now = now or dt.datetime.now(dt.timezone.utc)
    return now.astimezone(SAO_PAULO).date()


def day_key(value: dt.date | dt.datetime) -> str:
    """Dia (em São Paulo, se for um instante) como "AAAA-MM-DD"."""
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        value = value.astimezone(SAO_PAULO).date()
    return value.isoformat()


def start_of_day(day: dt.date) -> dt.datetime:
    """00:00 do dia em São Paulo (instante com fuso)."""
    return dt.datetime.combine(day, dt.time.min, tzinfo=SAO_PAULO)


@dataclass(frozen=True)
class PeriodRange:
    days: int
    start_day: dt.date  # primeiro dia do período (inclui hoje: 30 dias = hoje + 29 anteriores)
    end_day: dt.date  # hoje
    start: dt.datetime  # 00:00 de start_day
    previous_start: dt.datetime  # início do período anterior, de mesma duração

    @property
    def start_key(self) -> str:
        return self.start_day.isoformat()

    @property
    def end_key(self) -> str:
        return self.end_day.isoformat()


def period_range(days: int, now: dt.datetime | None = None) -> PeriodRange:
    end_day = sao_paulo_today(now)
    start_day = end_day - dt.timedelta(days=days - 1)
    return PeriodRange(
        days=days,
        start_day=start_day,
        end_day=end_day,
        start=start_of_day(start_day),
        previous_start=start_of_day(start_day - dt.timedelta(days=days)),
    )


def today_range(now: dt.datetime | None = None) -> tuple[dt.datetime, dt.datetime]:
    """(início de hoje, início de ontem) em São Paulo."""
    today = sao_paulo_today(now)
    return start_of_day(today), start_of_day(today - dt.timedelta(days=1))


def fill_timeline(counts: Mapping[str, int], start_key: str, end_key: str) -> list[dict]:
    """Série diária completa entre as duas datas (inclusive); dias sem cadastro ficam com 0."""
    start = dt.date.fromisoformat(start_key)
    end = dt.date.fromisoformat(end_key)
    points: list[dict] = []
    day = start
    while day <= end and len(points) < 4000:
        key = day.isoformat()
        points.append({"date": key, "count": int(counts.get(key, 0))})
        day += dt.timedelta(days=1)
    return points


def build_timeline(instants: Iterable[dt.datetime], start_key: str, end_key: str) -> list[dict]:
    """Agrupa instantes por dia (São Paulo) e preenche os dias vazios."""
    counts = Counter(day_key(i) for i in instants)
    return fill_timeline(counts, start_key, end_key)


def compare_periods(current: int, previous: int) -> dict:
    """Período atual x anterior: variação percentual (None quando o anterior é zero) e tendência."""
    delta = round((current - previous) / previous * 100, 1) if previous > 0 else None
    trend = "up" if current > previous else "down" if current < previous else "flat"
    return {"current": current, "previous": previous, "delta_pct": delta, "trend": trend}


def percent(part: float, whole: float | None) -> float | None:
    """Percentual com 1 casa; None quando o total é zero/ausente."""
    if not whole or whole <= 0:
        return None
    return round(part / whole * 1000) / 10


# ---------------------------------------------------------------------------------------------
# Faixas etárias
# ---------------------------------------------------------------------------------------------

AGE_MIN = 16
AGE_BUCKETS = (
    {"key": "16-24", "label": "16–24", "min": 16, "max": 24},
    {"key": "25-34", "label": "25–34", "min": 25, "max": 34},
    {"key": "35-44", "label": "35–44", "min": 35, "max": 44},
    {"key": "45-59", "label": "45–59", "min": 45, "max": 59},
    {"key": "60+", "label": "60+", "min": 60, "max": None},
)
AGE_UNKNOWN = {"key": "unknown", "label": "Não informado"}


def minus_years(day: dt.date, years: int) -> dt.date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 29/02
        return day.replace(year=day.year - years, day=28)


def age_at(birth: dt.date, today: dt.date) -> int:
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def age_bucket_key(age: int | None) -> str:
    """Faixa de uma idade (None ou menor que 16 → "unknown")."""
    if age is None or age < AGE_MIN:
        return AGE_UNKNOWN["key"]
    for bucket in AGE_BUCKETS:
        if age >= bucket["min"] and (bucket["max"] is None or age <= bucket["max"]):
            return bucket["key"]
    return AGE_UNKNOWN["key"]


def birth_date_bounds(min_age: int, max_age: int | None, today: dt.date) -> tuple[dt.date, dt.date | None]:
    """Limites de nascimento para "idade entre min e max": (nasc <= lte) e (nasc > gt, se houver).

    idade >= min  ⇔  nascimento <= hoje − min anos;  idade <= max  ⇔  nascimento > hoje − (max+1) anos.
    """
    lte = minus_years(today, min_age)
    gt = minus_years(today, max_age + 1) if max_age is not None else None
    return lte, gt


def bucket_ages(birth_dates: Iterable[dt.date | None], today: dt.date) -> list[dict]:
    """Conta datas de nascimento por faixa (conferência das contagens feitas no banco)."""
    counts: Counter[str] = Counter()
    for birth in birth_dates:
        counts[age_bucket_key(age_at(birth, today) if birth else None)] += 1
    return [{"key": b["key"], "label": b["label"], "count": counts.get(b["key"], 0)} for b in (*AGE_BUCKETS, AGE_UNKNOWN)]


# ---------------------------------------------------------------------------------------------
# Distribuições e listas
# ---------------------------------------------------------------------------------------------


def to_distribution(
    rows: Iterable[tuple[str | None, int]],
    order: Sequence[str],
    labels: Mapping[str, str],
    unknown_label: str = "Não informado",
) -> dict:
    """Distribuição em ordem fixa (todas as categorias, mesmo com 0); valores vazios/desconhecidos → "unknown" (omitido se 0)."""
    counts: Counter[str] = Counter()
    unknown = 0
    total = 0
    for value, count in rows:
        total += count
        if value and value in order:
            counts[value] += count
        else:
            unknown += count
    out = [{"key": k, "label": labels.get(k, k), "count": counts.get(k, 0)} for k in order]
    if unknown:
        out.append({"key": "unknown", "label": unknown_label, "count": unknown})
    return {"rows": out, "total": total}


def top_n(rows: Iterable[tuple[str | None, int]], limit: int) -> dict:
    """Top N por contagem. Agrupa grafias equivalentes (caixa/acentos) usando a mais frequente como rótulo.

    Retorna as linhas, a soma do restante (`others`, em `others_categories` categorias), os sem valor (`missing`) e o total.
    """
    merged: dict[str, dict[str, Any]] = {}
    missing = 0
    total = 0
    for value, count in rows:
        total += count
        text = (value or "").strip()
        if not text:
            missing += count
            continue
        norm = normalize_text(text)
        entry = merged.setdefault(norm, {"count": 0, "spellings": Counter()})
        entry["count"] += count
        entry["spellings"][text] += count
    ranked = []
    for entry in merged.values():
        label = max(entry["spellings"].items(), key=lambda kv: (kv[1], kv[0]))[0]
        ranked.append({"key": label, "label": label, "count": entry["count"]})
    ranked.sort(key=lambda r: (-r["count"], normalize_text(r["label"])))
    limit = max(0, limit)
    top, rest = ranked[:limit], ranked[limit:]
    return {
        "rows": top,
        "others": sum(r["count"] for r in rest),
        "others_categories": len(rest),
        "missing": missing,
        "total": total,
    }


# ---------------------------------------------------------------------------------------------
# Equipe e rankings
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TeamMember:
    id: str
    name: str
    role: str
    active: bool
    goal: int | None
    parent_id: str | None = None
    parent_name: str | None = None
    parent_role: str | None = None


@dataclass
class RegistrantStats:
    total: dict[str, int]
    in_period: dict[str, int]
    last_at: dict[str, dt.datetime | None]


def _name_key(name: str) -> str:
    return normalize_text(name)


def filter_members_by_voter_filters(members: Sequence[TeamMember], filters: Mapping[str, Any] | None) -> list[TeamMember]:
    """Restringe a equipe aos membros selecionados nos filtros do widget ("cadastrado por" / coordenadores)."""
    out = list(members)
    if not filters:
        return out
    if ids := filters.get("registered_by_ids"):
        wanted = set(ids)
        out = [m for m in out if m.id in wanted]
    if ids := filters.get("coordinator_ids"):
        wanted = set(ids)
        out = [m for m in out if m.id in wanted or (m.parent_id is not None and m.parent_id in wanted)]
    return out


def compute_member_ranking(members: Sequence[TeamMember], stats: RegistrantStats) -> list[dict]:
    """Ranking de cadastros por membro.

    Entram quem tem cadastros e os ativos que ainda não cadastraram (administrador sem cadastros fica de fora).
    Ordem: cadastros no período ↓, total ↓, nome.
    """
    rows = []
    for m in members:
        total = stats.total.get(m.id, 0)
        if total == 0 and (not m.active or m.role == Role.ADMIN):
            continue
        goal = m.goal if m.goal and m.goal > 0 else None
        last = stats.last_at.get(m.id)
        rows.append(
            {
                "id": m.id,
                "name": m.name,
                "role": m.role,
                "active": m.active,
                "coordinator_name": m.parent_name if m.role == Role.CABO and m.parent_role == Role.COORDENADOR else None,
                "total": total,
                "in_period": stats.in_period.get(m.id, 0),
                "goal": goal,
                "goal_pct": percent(total, goal) if goal else None,
                "last_at": last.isoformat() if last else None,
            }
        )
    rows.sort(key=lambda r: (-r["in_period"], -r["total"], _name_key(r["name"])))
    return rows


def compute_coordinator_ranking(members: Sequence[TeamMember], stats: RegistrantStats) -> dict:
    """Ranking por coordenador: soma os cadastros dele e dos cabos diretamente abaixo.

    Cadastros de quem não pertence à rede de nenhum coordenador vão para `others`.
    """
    coordinators = [m for m in members if m.role == Role.COORDENADOR]
    by_coord: dict[str, dict] = {}
    for c in coordinators:
        own = stats.total.get(c.id, 0)
        by_coord[c.id] = {
            "id": c.id,
            "name": c.name,
            "active": c.active,
            "cabos": 0,
            "own": own,
            "total": own,
            "in_period": stats.in_period.get(c.id, 0),
            "goal": None,
            "goal_pct": None,
        }
    cabo_goals: dict[str, int] = {}
    others_total = others_period = 0
    for m in members:
        if m.id in by_coord:
            continue
        total = stats.total.get(m.id, 0)
        in_period = stats.in_period.get(m.id, 0)
        row = by_coord.get(m.parent_id) if m.parent_id else None
        if row is not None:
            if m.active:
                row["cabos"] += 1
            row["total"] += total
            row["in_period"] += in_period
            if m.active and m.goal and m.goal > 0:
                cabo_goals[row["id"]] = cabo_goals.get(row["id"], 0) + m.goal
        else:
            others_total += total
            others_period += in_period
    goals = {c.id: c.goal for c in coordinators}
    for row in by_coord.values():
        own_goal = goals.get(row["id"])
        goal = own_goal if own_goal and own_goal > 0 else (cabo_goals.get(row["id"]) or None)
        row["goal"] = goal
        row["goal_pct"] = percent(row["total"], goal) if goal else None
    rows = sorted(by_coord.values(), key=lambda r: (-r["in_period"], -r["total"], _name_key(r["name"])))
    others = {"total": others_total, "in_period": others_period} if (others_total or others_period) else None
    return {"rows": rows, "others": others}


def compute_goals_progress(members: Sequence[TeamMember], totals: Mapping[str, int]) -> dict:
    """Progresso das metas individuais (só membros ativos com meta), maior percentual primeiro."""
    rows = []
    without_goal = 0
    for m in members:
        if not m.active:
            continue
        if not m.goal or m.goal <= 0:
            if m.role != Role.ADMIN:
                without_goal += 1
            continue
        total = totals.get(m.id, 0)
        rows.append(
            {"id": m.id, "name": m.name, "role": m.role, "total": total, "goal": m.goal, "pct": percent(total, m.goal) or 0}
        )
    rows.sort(key=lambda r: (-r["pct"], -r["total"], _name_key(r["name"])))
    return {"rows": rows, "without_goal": without_goal}


def team_goal_sum(members: Iterable[TeamMember]) -> tuple[int, int]:
    """(soma das metas individuais, quantos membros ativos têm meta)."""
    goal = count = 0
    for m in members:
        if m.active and m.goal and m.goal > 0:
            goal += m.goal
            count += 1
    return goal, count


def broadcast_rates(counts: Mapping[str, int]) -> dict:
    """Totais acumulados por status e taxas de entrega (entregues/enviadas) e de leitura (lidas/entregues)."""
    n = lambda key: int(counts.get(key, 0))  # noqa: E731
    read = n("READ")
    delivered = n("DELIVERED") + read
    sent = n("SENT") + delivered
    return {
        "sent": sent,
        "delivered": delivered,
        "read": read,
        "failed": n("FAILED"),
        "pending": n("PENDING") + n("SENDING"),
        "delivery_rate": percent(delivered, sent),
        "read_rate": percent(read, delivered),
    }
