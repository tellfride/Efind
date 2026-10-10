// Cálculo dos dados dos widgets. Toda consulta de eleitores passa por buildVoterWhere(user, filtros),
// portanto respeita a campanha e o escopo hierárquico de quem está vendo o dashboard.
import { prisma, type Prisma } from "@/lib/db";
import type { CampaignUser } from "@/lib/auth";
import { can } from "@/lib/permissions";
import {
  BROADCAST_STATUSES,
  GENDERS,
  GENDER_LABELS,
  SUPPORT_LEVELS,
  SUPPORT_LEVEL_LABELS,
  VOTER_SOURCES,
  VOTER_SOURCE_LABELS,
  type BroadcastStatus,
  type CampaignRole,
} from "@/lib/constants";
import {
  effectiveLimit,
  effectivePeriod,
  widgetDataKey,
  type DashboardDataResponse,
  type DashboardWidget,
  type WidgetData,
  type WidgetResult,
} from "@/lib/dashboard-types";
import type { VoterFilters } from "@/lib/voter-filters";
import { MESSAGEABLE_WHERE, buildVoterWhere, teamScopeWhere } from "@/server/access";
import {
  AGE_BUCKETS,
  AGE_UNKNOWN,
  birthDateBounds,
  broadcastRates,
  buildTimeline,
  comparePeriods,
  computeCoordinatorRanking,
  computeGoalsProgress,
  computeMemberRanking,
  filterMembersByVoterFilters,
  percent,
  periodRange,
  toDistribution,
  todayRange,
  topN,
  type RegistrantStats,
  type TeamMember,
} from "./aggregate";

/** Cache por requisição: evita refazer o escopo/equipe para cada widget */
export interface DashboardDataContext {
  user: CampaignUser;
  now: Date;
  voterWhere(filters?: VoterFilters): Promise<Prisma.VoterWhereInput>;
  team(): Promise<TeamMember[]>;
  campaignGoal(): Promise<number | null>;
}

export function createDataContext(user: CampaignUser, now: Date = new Date()): DashboardDataContext {
  const whereCache = new Map<string, Promise<Prisma.VoterWhereInput>>();
  let teamPromise: Promise<TeamMember[]> | null = null;
  let goalPromise: Promise<number | null> | null = null;
  return {
    user,
    now,
    voterWhere(filters = {}) {
      const key = JSON.stringify(filters);
      let p = whereCache.get(key);
      if (!p) {
        p = buildVoterWhere(user, filters);
        whereCache.set(key, p);
      }
      return p;
    },
    team() {
      teamPromise ??= prisma.user
        .findMany({
          where: teamScopeWhere(user),
          select: {
            id: true,
            name: true,
            role: true,
            active: true,
            goal: true,
            parentId: true,
            parent: { select: { name: true, role: true } },
          },
          orderBy: { name: "asc" },
          take: 2000,
        })
        .then((rows) =>
          rows.map((r) => ({
            id: r.id,
            name: r.name,
            role: r.role as CampaignRole,
            active: r.active,
            goal: r.goal,
            parentId: r.parentId,
            parentName: r.parent?.name ?? null,
            parentRole: r.parent?.role ?? null,
          })),
        );
      return teamPromise;
    },
    campaignGoal() {
      goalPromise ??= prisma.campaign
        .findUnique({ where: { id: user.campaignId }, select: { voterGoal: true } })
        .then((c) => c?.voterGoal ?? null);
      return goalPromise;
    },
  };
}

const and = (...parts: Prisma.VoterWhereInput[]): Prisma.VoterWhereInput => ({ AND: parts });

/** Estatísticas por quem cadastrou (total, no período e último cadastro) — 2 consultas agregadas */
async function registrantStats(where: Prisma.VoterWhereInput, start: Date): Promise<RegistrantStats> {
  const [all, period] = await Promise.all([
    prisma.voter.groupBy({ by: ["registeredById"], where, _count: { _all: true }, _max: { createdAt: true } }),
    prisma.voter.groupBy({ by: ["registeredById"], where: and(where, { createdAt: { gte: start } }), _count: { _all: true } }),
  ]);
  return {
    total: new Map(all.map((r) => [r.registeredById, r._count._all])),
    lastAt: new Map(all.map((r) => [r.registeredById, r._max.createdAt])),
    inPeriod: new Map(period.map((r) => [r.registeredById, r._count._all])),
  };
}

async function teamGoalSum(ctx: DashboardDataContext): Promise<{ goal: number; members: number }> {
  const team = await ctx.team();
  let goal = 0;
  let members = 0;
  for (const m of team) {
    if (m.active && m.goal && m.goal > 0) {
      goal += m.goal;
      members++;
    }
  }
  return { goal, members };
}

/** Calcula os dados de um widget dentro do escopo do usuário */
export async function computeWidgetData(
  user: CampaignUser,
  widget: DashboardWidget,
  ctx: DashboardDataContext = createDataContext(user),
): Promise<WidgetData> {
  const filters = widget.config.filters;
  const now = ctx.now;

  switch (widget.type) {
    case "kpi_total": {
      const where = await ctx.voterWhere(filters);
      const { start } = periodRange(7, now);
      const [total, last7] = await Promise.all([
        prisma.voter.count({ where }),
        prisma.voter.count({ where: and(where, { createdAt: { gte: start } }) }),
      ]);
      return { type: "kpi_total", total, last7 };
    }

    case "kpi_today": {
      const where = await ctx.voterWhere(filters);
      const { today, yesterday } = todayRange(now);
      const [t, y] = await Promise.all([
        prisma.voter.count({ where: and(where, { createdAt: { gte: today } }) }),
        prisma.voter.count({ where: and(where, { createdAt: { gte: yesterday, lt: today } }) }),
      ]);
      return { type: "kpi_today", today: t, yesterday: y };
    }

    case "kpi_period": {
      const period = effectivePeriod(widget);
      const where = await ctx.voterWhere(filters);
      const range = periodRange(period, now);
      const [current, previous] = await Promise.all([
        prisma.voter.count({ where: and(where, { createdAt: { gte: range.start } }) }),
        prisma.voter.count({ where: and(where, { createdAt: { gte: range.previousStart, lt: range.start } }) }),
      ]);
      return { type: "kpi_period", period, comparison: comparePeriods(current, previous) };
    }

    case "kpi_goal": {
      const where = await ctx.voterWhere(filters);
      const total = await prisma.voter.count({ where });
      if (user.role === "ADMIN") {
        const goal = await ctx.campaignGoal();
        const { members } = await teamGoalSum(ctx);
        return { type: "kpi_goal", total, goal, pct: percent(total, goal), source: "campaign", membersWithGoal: members };
      }
      const { goal, members } = await teamGoalSum(ctx);
      return {
        type: "kpi_goal",
        total,
        goal: goal > 0 ? goal : null,
        pct: percent(total, goal),
        source: "team",
        membersWithGoal: members,
      };
    }

    case "kpi_messageable": {
      const where = await ctx.voterWhere(filters);
      const [messageable, total] = await Promise.all([
        prisma.voter.count({ where: and(where, MESSAGEABLE_WHERE) }),
        prisma.voter.count({ where }),
      ]);
      return { type: "kpi_messageable", messageable, total, pct: percent(messageable, total) };
    }

    case "kpi_team": {
      const period = effectivePeriod(widget);
      const where = await ctx.voterWhere(filters);
      const { start } = periodRange(period, now);
      const [team, groups] = await Promise.all([
        ctx.team(),
        prisma.voter.groupBy({ by: ["registeredById"], where: and(where, { createdAt: { gte: start } }), _count: { _all: true } }),
      ]);
      const members = filterMembersByVoterFilters(team, filters).filter((m) => m.active);
      const activeIds = new Set(members.map((m) => m.id));
      const contributing = groups.filter((g) => activeIds.has(g.registeredById)).length;
      return { type: "kpi_team", period, active: members.length, contributing, pct: percent(contributing, members.length) };
    }

    case "ranking_members": {
      const period = effectivePeriod(widget);
      const where = await ctx.voterWhere(filters);
      const { start } = periodRange(period, now);
      const [team, stats] = await Promise.all([ctx.team(), registrantStats(where, start)]);
      const rows = computeMemberRanking(filterMembersByVoterFilters(team, filters), stats);
      let total = 0;
      let periodTotal = 0;
      for (const v of stats.total.values()) total += v;
      for (const v of stats.inPeriod.values()) periodTotal += v;
      const contributing = [...stats.inPeriod.values()].filter((v) => v > 0).length;
      // A lista completa vai para o cliente (ordenação/“ver todos”); limite de segurança
      return { type: "ranking_members", period, rows: rows.slice(0, 500), total, periodTotal, contributing };
    }

    case "ranking_coordinators": {
      const period = effectivePeriod(widget);
      if (user.role === "CABO") return { type: "ranking_coordinators", period, applicable: false, rows: [], others: null };
      const where = await ctx.voterWhere(filters);
      const { start } = periodRange(period, now);
      const [team, stats] = await Promise.all([ctx.team(), registrantStats(where, start)]);
      const { rows, others } = computeCoordinatorRanking(team, stats);
      const selected = filters?.coordinatorIds?.length ? rows.filter((r) => filters.coordinatorIds!.includes(r.id)) : rows;
      return {
        type: "ranking_coordinators",
        period,
        applicable: true,
        rows: selected.slice(0, 200),
        others: filters?.coordinatorIds?.length ? null : others,
      };
    }

    case "timeline": {
      const period = effectivePeriod(widget);
      const where = await ctx.voterWhere(filters);
      const range = periodRange(period, now);
      const [rows, previousTotal] = await Promise.all([
        prisma.voter.findMany({ where: and(where, { createdAt: { gte: range.start } }), select: { createdAt: true } }),
        prisma.voter.count({ where: and(where, { createdAt: { gte: range.previousStart, lt: range.start } }) }),
      ]);
      const points = buildTimeline(
        rows.map((r) => r.createdAt),
        range.startKey,
        range.endKey,
      );
      return { type: "timeline", period, points, total: rows.length, previousTotal };
    }

    case "by_neighborhood": {
      const where = await ctx.voterWhere(filters);
      const groups = await prisma.voter.groupBy({ by: ["neighborhood"], where, _count: { _all: true } });
      const top = topN(
        groups.map((g) => ({ value: g.neighborhood, count: g._count._all })),
        effectiveLimit(widget),
      );
      return { type: "by_neighborhood", ...top };
    }

    case "by_city": {
      const where = await ctx.voterWhere(filters);
      const groups = await prisma.voter.groupBy({ by: ["city"], where, _count: { _all: true } });
      const top = topN(
        groups.map((g) => ({ value: g.city, count: g._count._all })),
        effectiveLimit(widget),
      );
      return { type: "by_city", ...top };
    }

    case "by_gender": {
      const where = await ctx.voterWhere(filters);
      const groups = await prisma.voter.groupBy({ by: ["gender"], where, _count: { _all: true } });
      const dist = toDistribution(
        groups.map((g) => ({ value: g.gender, count: g._count._all })),
        GENDERS,
        GENDER_LABELS,
      );
      return { type: "by_gender", ...dist };
    }

    case "by_support": {
      const where = await ctx.voterWhere(filters);
      const groups = await prisma.voter.groupBy({ by: ["supportLevel"], where, _count: { _all: true } });
      const dist = toDistribution(
        groups.map((g) => ({ value: g.supportLevel, count: g._count._all })),
        SUPPORT_LEVELS,
        SUPPORT_LEVEL_LABELS,
        "Sem classificação",
      );
      return { type: "by_support", ...dist };
    }

    case "by_source": {
      const where = await ctx.voterWhere(filters);
      const groups = await prisma.voter.groupBy({ by: ["source"], where, _count: { _all: true } });
      const dist = toDistribution(
        groups.map((g) => ({ value: g.source, count: g._count._all })),
        VOTER_SOURCES,
        VOTER_SOURCE_LABELS,
      );
      return { type: "by_source", ...dist };
    }

    case "by_age": {
      const where = await ctx.voterWhere(filters);
      const youngest = birthDateBounds(16, null, now).lte;
      const counts = await Promise.all([
        ...AGE_BUCKETS.map((b) => {
          const bounds = birthDateBounds(b.min, b.max, now);
          return prisma.voter.count({ where: and(where, { birthDate: { lte: bounds.lte, ...(bounds.gt ? { gt: bounds.gt } : {}) } }) });
        }),
        // Sem data de nascimento ou com idade inválida (menos de 16 anos)
        prisma.voter.count({ where: and(where, { OR: [{ birthDate: null }, { birthDate: { gt: youngest } }] }) }),
      ]);
      const rows = [...AGE_BUCKETS, AGE_UNKNOWN].map((b, i) => ({ key: b.key, label: b.label, count: counts[i] }));
      return { type: "by_age", rows, total: counts.reduce((s, c) => s + c, 0) };
    }

    case "recent_voters": {
      if (!can(user.permissions, "eleitores", "view")) return { type: "recent_voters", locked: true, rows: [] };
      const where = await ctx.voterWhere(filters);
      const rows = await prisma.voter.findMany({
        where,
        orderBy: { createdAt: "desc" },
        take: effectiveLimit(widget),
        select: {
          id: true,
          name: true,
          neighborhood: true,
          city: true,
          createdAt: true,
          registeredBy: { select: { name: true } },
        },
      });
      return {
        type: "recent_voters",
        locked: false,
        rows: rows.map((r) => ({
          id: r.id,
          name: r.name,
          neighborhood: r.neighborhood,
          city: r.city,
          registeredBy: r.registeredBy.name,
          createdAt: r.createdAt.toISOString(),
        })),
      };
    }

    case "broadcasts": {
      const period = effectivePeriod(widget);
      const isAdmin = user.role === "ADMIN";
      const empty = { sent: 0, delivered: 0, read: 0, failed: 0, pending: 0, deliveryRate: null, readRate: null, recent: [] };
      if (!can(user.permissions, "disparos", "view")) {
        return { type: "broadcasts", locked: true, period, scope: isAdmin ? "campaign" : "own", ...empty };
      }
      const { start } = periodRange(period, now);
      // Não-administradores veem apenas os disparos que criaram
      const broadcastWhere: Prisma.BroadcastWhereInput = isAdmin
        ? { campaignId: user.campaignId }
        : { campaignId: user.campaignId, createdById: user.id };
      const messageWhere: Prisma.BroadcastMessageWhereInput = isAdmin
        ? { campaignId: user.campaignId, createdAt: { gte: start } }
        : { campaignId: user.campaignId, createdAt: { gte: start }, broadcast: { createdById: user.id } };
      const [groups, recent] = await Promise.all([
        prisma.broadcastMessage.groupBy({ by: ["status"], where: messageWhere, _count: { _all: true } }),
        prisma.broadcast.findMany({
          where: broadcastWhere,
          orderBy: { createdAt: "desc" },
          take: 5,
          select: {
            id: true,
            name: true,
            status: true,
            totalRecipients: true,
            sentCount: true,
            deliveredCount: true,
            readCount: true,
            failedCount: true,
            createdAt: true,
          },
        }),
      ]);
      const counts: Record<string, number> = {};
      for (const g of groups) counts[g.status] = g._count._all;
      return {
        type: "broadcasts",
        locked: false,
        period,
        scope: isAdmin ? "campaign" : "own",
        ...broadcastRates(counts),
        recent: recent.map((b) => ({
          ...b,
          status: ((BROADCAST_STATUSES as readonly string[]).includes(b.status) ? b.status : "DRAFT") as BroadcastStatus,
          createdAt: b.createdAt.toISOString(),
        })),
      };
    }

    case "goals_progress": {
      const where = await ctx.voterWhere(filters);
      const [team, groups] = await Promise.all([
        ctx.team(),
        prisma.voter.groupBy({ by: ["registeredById"], where, _count: { _all: true } }),
      ]);
      const totals = new Map(groups.map((g) => [g.registeredById, g._count._all]));
      const { rows, withoutGoal } = computeGoalsProgress(filterMembersByVoterFilters(team, filters), totals);
      return { type: "goals_progress", rows: rows.slice(0, effectiveLimit(widget)), withoutGoal };
    }

    case "note":
      return { type: "note" };
  }
}

/** Calcula vários widgets de uma vez; widgets com os mesmos dados são calculados uma única vez */
export async function computeDashboardData(user: CampaignUser, widgets: DashboardWidget[]): Promise<DashboardDataResponse> {
  const ctx = createDataContext(user);
  const byKey = new Map<string, Promise<WidgetResult>>();
  const entries = await Promise.all(
    widgets.map(async (widget) => {
      const key = widgetDataKey(widget);
      let p = byKey.get(key);
      if (!p) {
        p = computeWidgetData(user, widget, ctx).catch((err: unknown) => {
          // Sem dados pessoais no log: apenas o tipo do widget e o tipo do erro
          const code = err && typeof err === "object" && "code" in err ? String((err as { code: unknown }).code) : "";
          console.error("[dashboard] falha ao calcular widget", widget.type, err instanceof Error ? err.name : "erro", code);
          return { error: "Não foi possível carregar este widget." };
        });
        byKey.set(key, p);
      }
      return [widget.id, await p] as const;
    }),
  );
  return Object.fromEntries(entries);
}
