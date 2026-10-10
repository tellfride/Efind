// Funções puras de agregação dos widgets (sem banco) — testadas em tests/dashboard*.test.ts.
import type { CampaignRole } from "@/lib/constants";
import type {
  CategoryCount,
  CoordinatorRankingRow,
  GoalProgressRow,
  MemberRankingRow,
  PeriodComparison,
  TimelinePoint,
} from "@/lib/dashboard-types";
import type { VoterFilters } from "@/lib/voter-filters";

export const TIME_ZONE = "America/Sao_Paulo";
const DAY_MS = 86_400_000;

// ---------- Datas (dias no fuso de São Paulo) ----------

const dayFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/** "yyyy-mm-dd" do dia (em America/Sao_Paulo) em que o instante cai */
export function saoPauloDayKey(date: Date): string {
  const parts = dayFormatter.formatToParts(date);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

/** Soma dias a uma chave "yyyy-mm-dd" (aritmética de calendário, sem fuso) */
export function addDaysToKey(key: string, days: number): string {
  const [y, m, d] = key.split("-").map(Number);
  const t = Date.UTC(y, m - 1, d) + days * DAY_MS;
  return new Date(t).toISOString().slice(0, 10);
}

/** Início do dia (00:00 em São Paulo, UTC−3 — sem horário de verão desde 2019) */
export function startOfSaoPauloDay(key: string): Date {
  return new Date(`${key}T00:00:00-03:00`);
}

export interface PeriodRange {
  /** Primeiro dia do período (inclui hoje: 30 dias = hoje e os 29 anteriores) */
  startKey: string;
  endKey: string;
  start: Date;
  /** Início do período anterior, de mesma duração */
  previousStart: Date;
}

export function periodRange(days: number, now: Date = new Date()): PeriodRange {
  const endKey = saoPauloDayKey(now);
  const startKey = addDaysToKey(endKey, -(days - 1));
  return {
    startKey,
    endKey,
    start: startOfSaoPauloDay(startKey),
    previousStart: startOfSaoPauloDay(addDaysToKey(startKey, -days)),
  };
}

/** Intervalos de hoje e ontem */
export function todayRange(now: Date = new Date()) {
  const todayKey = saoPauloDayKey(now);
  const today = startOfSaoPauloDay(todayKey);
  const yesterday = startOfSaoPauloDay(addDaysToKey(todayKey, -1));
  return { today, yesterday };
}

/** Série diária completa entre startKey e endKey (inclusive); dias sem cadastro ficam com 0 */
export function fillTimeline(counts: Map<string, number> | Record<string, number>, startKey: string, endKey: string): TimelinePoint[] {
  const get = (k: string) => (counts instanceof Map ? counts.get(k) : counts[k]) ?? 0;
  const points: TimelinePoint[] = [];
  if (startKey > endKey) return points;
  for (let key = startKey, guard = 0; key <= endKey && guard < 4000; key = addDaysToKey(key, 1), guard++) {
    points.push({ date: key, count: get(key) });
  }
  return points;
}

/** Agrupa instantes por dia (São Paulo) e preenche os dias vazios */
export function buildTimeline(dates: Date[], startKey: string, endKey: string): TimelinePoint[] {
  const counts = new Map<string, number>();
  for (const d of dates) {
    const key = saoPauloDayKey(d);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return fillTimeline(counts, startKey, endKey);
}

// ---------- Comparação de períodos ----------

export function comparePeriods(current: number, previous: number): PeriodComparison {
  const deltaPct = previous > 0 ? ((current - previous) / previous) * 100 : null;
  const trend = current > previous ? "up" : current < previous ? "down" : "flat";
  return { current, previous, deltaPct: deltaPct === null ? null : Math.round(deltaPct * 10) / 10, trend };
}

/** Percentual arredondado a 1 casa; null quando o denominador é zero/ausente */
export function percent(part: number, whole: number | null | undefined): number | null {
  if (!whole || whole <= 0) return null;
  return Math.round((part / whole) * 1000) / 10;
}

// ---------- Faixas etárias ----------

export const AGE_BUCKETS = [
  { key: "16-24", label: "16–24", min: 16, max: 24 },
  { key: "25-34", label: "25–34", min: 25, max: 34 },
  { key: "35-44", label: "35–44", min: 35, max: 44 },
  { key: "45-59", label: "45–59", min: 45, max: 59 },
  { key: "60+", label: "60+", min: 60, max: null },
] as const;
export const AGE_UNKNOWN = { key: "unknown", label: "Não informado" } as const;

/** Faixa de uma idade (null/menor que 16 → "Não informado") */
export function ageBucketKey(age: number | null | undefined): string {
  if (age === null || age === undefined || !Number.isFinite(age) || age < 16) return AGE_UNKNOWN.key;
  for (const b of AGE_BUCKETS) if (age >= b.min && (b.max === null || age <= b.max)) return b.key;
  return AGE_UNKNOWN.key;
}

/** Idade em anos completos numa data de referência (calendário local do servidor) */
export function ageAt(birthDate: Date, now: Date): number {
  let age = now.getFullYear() - birthDate.getFullYear();
  const m = now.getMonth() - birthDate.getMonth();
  if (m < 0 || (m === 0 && now.getDate() < birthDate.getDate())) age--;
  return age;
}

/**
 * Limites de data de nascimento para "idade entre min e max" (mesma regra de src/server/access.ts):
 *   idade >= min ⇔ nascimento <= hoje − min anos;  idade <= max ⇔ nascimento > hoje − (max+1) anos.
 */
export function birthDateBounds(min: number, max: number | null, now: Date): { lte: Date; gt?: Date } {
  const lte = new Date(now.getFullYear() - min, now.getMonth(), now.getDate(), 23, 59, 59);
  if (max === null) return { lte };
  const gt = new Date(now.getFullYear() - max - 1, now.getMonth(), now.getDate(), 23, 59, 59);
  return { lte, gt };
}

/** Conta idades em faixas (útil para conferir as contagens feitas no banco) */
export function bucketAges(birthDates: (Date | null)[], now: Date): CategoryCount[] {
  const counts = new Map<string, number>();
  for (const b of birthDates) {
    const key = ageBucketKey(b ? ageAt(b, now) : null);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return [...AGE_BUCKETS, AGE_UNKNOWN].map((b) => ({ key: b.key, label: b.label, count: counts.get(b.key) ?? 0 }));
}

// ---------- Distribuições e listas ----------

/** Distribuição em ordem fixa, com "Não informado" para valores nulos/desconhecidos (omitido se zero) */
export function toDistribution(
  rows: { value: string | null; count: number }[],
  order: readonly string[],
  labels: Record<string, string>,
  unknownLabel = "Não informado",
): { rows: CategoryCount[]; total: number } {
  const counts = new Map<string, number>();
  let unknown = 0;
  let total = 0;
  for (const r of rows) {
    total += r.count;
    if (r.value && order.includes(r.value)) counts.set(r.value, (counts.get(r.value) ?? 0) + r.count);
    else unknown += r.count;
  }
  const out: CategoryCount[] = order.map((k) => ({ key: k, label: labels[k] ?? k, count: counts.get(k) ?? 0 }));
  if (unknown > 0) out.push({ key: "unknown", label: unknownLabel, count: unknown });
  return { rows: out, total };
}

/** Top N por contagem (empate: ordem alfabética), somando o restante em "outros" */
export function topN(rows: { value: string | null; count: number }[], limit: number) {
  const merged = new Map<string, number>();
  let missing = 0;
  let total = 0;
  for (const r of rows) {
    total += r.count;
    const v = r.value?.trim();
    if (!v) {
      missing += r.count;
      continue;
    }
    merged.set(v, (merged.get(v) ?? 0) + r.count);
  }
  const sorted = [...merged.entries()]
    .map(([label, count]) => ({ key: label, label, count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, "pt-BR"));
  const top = sorted.slice(0, Math.max(0, limit));
  const rest = sorted.slice(top.length);
  return {
    rows: top,
    others: rest.reduce((s, r) => s + r.count, 0),
    othersCategories: rest.length,
    missing,
    total,
  };
}

// ---------- Equipe e rankings ----------

export interface TeamMember {
  id: string;
  name: string;
  role: CampaignRole;
  active: boolean;
  goal: number | null;
  parentId: string | null;
  parentName: string | null;
  parentRole: string | null;
}

export interface RegistrantStats {
  total: Map<string, number>;
  inPeriod: Map<string, number>;
  lastAt: Map<string, Date | null>;
}

/** Restringe a equipe aos membros selecionados nos filtros do widget ("cadastrado por" / coordenadores) */
export function filterMembersByVoterFilters(members: TeamMember[], filters: VoterFilters | undefined): TeamMember[] {
  if (!filters) return members;
  let out = members;
  if (filters.registeredByIds?.length) {
    const ids = new Set(filters.registeredByIds);
    out = out.filter((m) => ids.has(m.id));
  }
  if (filters.coordinatorIds?.length) {
    const ids = new Set(filters.coordinatorIds);
    out = out.filter((m) => ids.has(m.id) || (m.parentId !== null && ids.has(m.parentId)));
  }
  return out;
}

/**
 * Ranking de cadastros por membro. Entram os membros com cadastros e os ativos que ainda não
 * cadastraram (exceto administradores sem cadastros, que só poluiriam a lista).
 * Ordem: cadastros no período ↓, total ↓, nome.
 */
export function computeMemberRanking(members: TeamMember[], stats: RegistrantStats): MemberRankingRow[] {
  const rows: MemberRankingRow[] = [];
  for (const m of members) {
    const total = stats.total.get(m.id) ?? 0;
    if (total === 0 && (!m.active || m.role === "ADMIN")) continue;
    const goal = m.goal && m.goal > 0 ? m.goal : null;
    const last = stats.lastAt.get(m.id) ?? null;
    rows.push({
      id: m.id,
      name: m.name,
      role: m.role,
      active: m.active,
      coordinatorName: m.role === "CABO" && m.parentRole === "COORDENADOR" ? m.parentName : null,
      total,
      inPeriod: stats.inPeriod.get(m.id) ?? 0,
      goal,
      goalPct: goal ? percent(total, goal) : null,
      lastAt: last ? last.toISOString() : null,
    });
  }
  return rows.sort((a, b) => b.inPeriod - a.inPeriod || b.total - a.total || a.name.localeCompare(b.name, "pt-BR"));
}

/**
 * Ranking por coordenador: soma os cadastros do coordenador e dos cabos diretamente abaixo dele.
 * Cadastros de quem não pertence a nenhuma rede de coordenador vão para "others".
 */
export function computeCoordinatorRanking(
  members: TeamMember[],
  stats: Pick<RegistrantStats, "total" | "inPeriod">,
): { rows: CoordinatorRankingRow[]; others: { total: number; inPeriod: number } | null } {
  const coordinators = members.filter((m) => m.role === "COORDENADOR");
  const coordIds = new Set(coordinators.map((c) => c.id));
  const byCoord = new Map<string, CoordinatorRankingRow>();
  for (const c of coordinators) {
    const own = stats.total.get(c.id) ?? 0;
    byCoord.set(c.id, {
      id: c.id,
      name: c.name,
      active: c.active,
      cabos: 0,
      own,
      total: own,
      inPeriod: stats.inPeriod.get(c.id) ?? 0,
      goal: null,
      goalPct: null,
    });
  }
  const caboGoals = new Map<string, number>();
  let othersTotal = 0;
  let othersPeriod = 0;
  for (const m of members) {
    if (coordIds.has(m.id)) continue;
    const total = stats.total.get(m.id) ?? 0;
    const inPeriod = stats.inPeriod.get(m.id) ?? 0;
    const row = m.parentId ? byCoord.get(m.parentId) : undefined;
    if (row) {
      if (m.active) row.cabos += 1;
      row.total += total;
      row.inPeriod += inPeriod;
      if (m.active && m.goal && m.goal > 0) caboGoals.set(row.id, (caboGoals.get(row.id) ?? 0) + m.goal);
    } else {
      othersTotal += total;
      othersPeriod += inPeriod;
    }
  }
  const rows = [...byCoord.values()].map((row) => {
    const coord = coordinators.find((c) => c.id === row.id);
    const goal = coord?.goal && coord.goal > 0 ? coord.goal : caboGoals.get(row.id) || null;
    return { ...row, goal, goalPct: goal ? percent(row.total, goal) : null };
  });
  rows.sort((a, b) => b.inPeriod - a.inPeriod || b.total - a.total || a.name.localeCompare(b.name, "pt-BR"));
  return { rows, others: othersTotal > 0 || othersPeriod > 0 ? { total: othersTotal, inPeriod: othersPeriod } : null };
}

/** Progresso das metas individuais (somente membros ativos com meta), maior percentual primeiro */
export function computeGoalsProgress(
  members: TeamMember[],
  totals: Map<string, number>,
): { rows: GoalProgressRow[]; withoutGoal: number } {
  const rows: GoalProgressRow[] = [];
  let withoutGoal = 0;
  for (const m of members) {
    if (!m.active) continue;
    if (!m.goal || m.goal <= 0) {
      if (m.role !== "ADMIN") withoutGoal++;
      continue;
    }
    const total = totals.get(m.id) ?? 0;
    rows.push({ id: m.id, name: m.name, role: m.role, total, goal: m.goal, pct: percent(total, m.goal) ?? 0 });
  }
  rows.sort((a, b) => b.pct - a.pct || b.total - a.total || a.name.localeCompare(b.name, "pt-BR"));
  return { rows, withoutGoal };
}

/** Taxas de entrega (entregues/enviadas) e leitura (lidas/entregues) */
export function broadcastRates(counts: Record<string, number>) {
  const n = (k: string) => counts[k] ?? 0;
  const read = n("READ");
  const delivered = n("DELIVERED") + read;
  const sent = n("SENT") + delivered;
  const failed = n("FAILED");
  const pending = n("PENDING") + n("SENDING");
  return {
    sent,
    delivered,
    read,
    failed,
    pending,
    deliveryRate: percent(delivered, sent),
    readRate: percent(read, delivered),
  };
}
