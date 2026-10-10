// Dashboards personalizáveis: tipos de widget, catálogo, validação e formato dos dados.
// Puro (sem banco) — usado no servidor (cálculo/salvamento) e nos componentes cliente (montador).
import { z } from "zod";
import { cleanVoterFilters, voterFiltersSchema, type VoterFilters } from "./voter-filters";
import type { BroadcastStatus, CampaignRole } from "./constants";

// ---------- Tipos básicos ----------

export const WIDGET_TYPES = [
  "kpi_total",
  "kpi_today",
  "kpi_period",
  "kpi_goal",
  "kpi_messageable",
  "kpi_team",
  "ranking_members",
  "ranking_coordinators",
  "timeline",
  "by_neighborhood",
  "by_city",
  "by_gender",
  "by_support",
  "by_source",
  "by_age",
  "recent_voters",
  "broadcasts",
  "goals_progress",
  "note",
] as const;
export type WidgetType = (typeof WIDGET_TYPES)[number];

export const WIDGET_SIZES = ["sm", "md", "lg", "full"] as const;
export type WidgetSize = (typeof WIDGET_SIZES)[number];
export const WIDGET_SIZE_LABELS: Record<WidgetSize, { short: string; long: string }> = {
  sm: { short: "P", long: "Pequeno (1 coluna)" },
  md: { short: "M", long: "Médio (2 colunas)" },
  lg: { short: "G", long: "Grande (3 colunas)" },
  full: { short: "Inteiro", long: "Largura inteira" },
};

export const WIDGET_PERIODS = [7, 30, 90, 365] as const;
export type WidgetPeriod = (typeof WIDGET_PERIODS)[number];
export const WIDGET_PERIOD_LABELS: Record<WidgetPeriod, string> = {
  7: "Últimos 7 dias",
  30: "Últimos 30 dias",
  90: "Últimos 90 dias",
  365: "Últimos 12 meses",
};
export const DEFAULT_WIDGET_PERIOD: WidgetPeriod = 30;

export const MAX_WIDGETS = 30;
export const MAX_NOTE_LENGTH = 2000;
export const MAX_WIDGET_TITLE = 80;

export interface WidgetConfig {
  period?: WidgetPeriod;
  limit?: number;
  filters?: VoterFilters;
  text?: string;
}

export interface DashboardWidget {
  id: string;
  type: WidgetType;
  title?: string;
  size: WidgetSize;
  config: WidgetConfig;
}

// ---------- Catálogo ----------

export const WIDGET_GROUPS = ["indicadores", "equipe", "territorio", "perfil", "whatsapp", "outros"] as const;
export type WidgetGroup = (typeof WIDGET_GROUPS)[number];
export const WIDGET_GROUP_LABELS: Record<WidgetGroup, string> = {
  indicadores: "Indicadores",
  equipe: "Equipe",
  territorio: "Território",
  perfil: "Perfil do eleitor",
  whatsapp: "WhatsApp",
  outros: "Outros",
};

/** Nomes de ícones lucide-react (mapeados para componentes em src/components/dashboard/widget-icons.ts) */
export type WidgetIconName =
  | "UsersRound"
  | "CalendarCheck"
  | "TrendingUp"
  | "Target"
  | "MessageCircle"
  | "Users"
  | "Trophy"
  | "Network"
  | "ChartArea"
  | "MapPin"
  | "Building2"
  | "ChartPie"
  | "HeartHandshake"
  | "QrCode"
  | "Cake"
  | "Clock"
  | "Send"
  | "Flag"
  | "Megaphone";

export interface LimitOption {
  min: number;
  max: number;
  default: number;
}

export interface WidgetDefinition {
  type: WidgetType;
  label: string;
  description: string;
  group: WidgetGroup;
  icon: WidgetIconName;
  defaultSize: WidgetSize;
  /** Opções configuráveis no modal de ajustes */
  options: {
    period?: boolean;
    limit?: LimitOption;
    filters?: boolean;
    text?: boolean;
  };
  /** Permissão de módulo (ação "view") exigida para ver os dados do widget */
  requires?: "eleitores" | "disparos";
}

export const WIDGET_CATALOG: Record<WidgetType, WidgetDefinition> = {
  kpi_total: {
    type: "kpi_total",
    label: "Total de eleitores",
    description: "Quantidade de eleitores cadastrados e o crescimento nos últimos 7 dias.",
    group: "indicadores",
    icon: "UsersRound",
    defaultSize: "sm",
    options: { filters: true },
  },
  kpi_today: {
    type: "kpi_today",
    label: "Cadastros hoje",
    description: "Cadastros feitos hoje, comparados com ontem.",
    group: "indicadores",
    icon: "CalendarCheck",
    defaultSize: "sm",
    options: { filters: true },
  },
  kpi_period: {
    type: "kpi_period",
    label: "Cadastros no período",
    description: "Cadastros no período escolhido e a variação em relação ao período anterior.",
    group: "indicadores",
    icon: "TrendingUp",
    defaultSize: "sm",
    options: { period: true, filters: true },
  },
  kpi_goal: {
    type: "kpi_goal",
    label: "Meta de cadastros",
    description: "Progresso em relação à meta da campanha (ou à soma das metas da sua equipe).",
    group: "indicadores",
    icon: "Target",
    defaultSize: "sm",
    options: { filters: true },
  },
  timeline: {
    type: "timeline",
    label: "Evolução dos cadastros",
    description: "Gráfico com os cadastros dia a dia no período.",
    group: "indicadores",
    icon: "ChartArea",
    defaultSize: "lg",
    options: { period: true, filters: true },
  },
  kpi_team: {
    type: "kpi_team",
    label: "Equipe ativa",
    description: "Membros ativos da equipe e quantos cadastraram eleitores no período.",
    group: "equipe",
    icon: "Users",
    defaultSize: "sm",
    options: { period: true, filters: true },
  },
  ranking_members: {
    type: "ranking_members",
    label: "Cadastros por cabo eleitoral",
    description: "Ranking da equipe: total, cadastros no período, meta e último cadastro de cada membro.",
    group: "equipe",
    icon: "Trophy",
    defaultSize: "full",
    options: { period: true, limit: { min: 3, max: 100, default: 10 }, filters: true },
  },
  ranking_coordinators: {
    type: "ranking_coordinators",
    label: "Desempenho por coordenador",
    description: "Cadastros de cada coordenador somados aos dos cabos eleitorais da sua rede.",
    group: "equipe",
    icon: "Network",
    defaultSize: "full",
    options: { period: true, limit: { min: 3, max: 50, default: 10 }, filters: true },
  },
  goals_progress: {
    type: "goals_progress",
    label: "Metas individuais",
    description: "Progresso de cada membro em relação à sua meta individual de cadastros.",
    group: "equipe",
    icon: "Flag",
    defaultSize: "md",
    options: { limit: { min: 3, max: 50, default: 10 }, filters: true },
  },
  by_neighborhood: {
    type: "by_neighborhood",
    label: "Eleitores por bairro",
    description: "Bairros com mais eleitores cadastrados.",
    group: "territorio",
    icon: "MapPin",
    defaultSize: "md",
    options: { limit: { min: 3, max: 30, default: 10 }, filters: true },
  },
  by_city: {
    type: "by_city",
    label: "Eleitores por cidade",
    description: "Cidades com mais eleitores cadastrados.",
    group: "territorio",
    icon: "Building2",
    defaultSize: "md",
    options: { limit: { min: 3, max: 30, default: 10 }, filters: true },
  },
  by_gender: {
    type: "by_gender",
    label: "Gênero",
    description: "Distribuição dos eleitores por gênero.",
    group: "perfil",
    icon: "ChartPie",
    defaultSize: "md",
    options: { filters: true },
  },
  by_support: {
    type: "by_support",
    label: "Nível de apoio",
    description: "Apoiadores, simpatizantes, indecisos e opositores.",
    group: "perfil",
    icon: "HeartHandshake",
    defaultSize: "md",
    options: { filters: true },
  },
  by_source: {
    type: "by_source",
    label: "Origem do cadastro",
    description: "Cadastros feitos por link, QR Code, manualmente ou por importação.",
    group: "perfil",
    icon: "QrCode",
    defaultSize: "md",
    options: { filters: true },
  },
  by_age: {
    type: "by_age",
    label: "Faixa etária",
    description: "Eleitores por faixa de idade (16–24, 25–34, 35–44, 45–59 e 60+).",
    group: "perfil",
    icon: "Cake",
    defaultSize: "md",
    options: { filters: true },
  },
  kpi_messageable: {
    type: "kpi_messageable",
    label: "Aptos a WhatsApp",
    description: "Eleitores que aceitaram receber mensagens e não pediram descadastro.",
    group: "whatsapp",
    icon: "MessageCircle",
    defaultSize: "sm",
    options: { filters: true },
  },
  broadcasts: {
    type: "broadcasts",
    label: "Disparos de WhatsApp",
    description: "Mensagens enviadas, entregues, lidas e com falha, além dos últimos disparos.",
    group: "whatsapp",
    icon: "Send",
    defaultSize: "full",
    options: { period: true },
    requires: "disparos",
  },
  recent_voters: {
    type: "recent_voters",
    label: "Últimos cadastros",
    description: "Os eleitores cadastrados mais recentemente e quem os cadastrou.",
    group: "outros",
    icon: "Clock",
    defaultSize: "md",
    options: { limit: { min: 3, max: 20, default: 8 }, filters: true },
    requires: "eleitores",
  },
  note: {
    type: "note",
    label: "Recado para a equipe",
    description: "Texto livre: avisos, orientações ou metas da semana.",
    group: "outros",
    icon: "Megaphone",
    defaultSize: "full",
    options: { text: true },
  },
};

export const KPI_TYPES: readonly WidgetType[] = [
  "kpi_total",
  "kpi_today",
  "kpi_period",
  "kpi_goal",
  "kpi_messageable",
  "kpi_team",
];
export function isKpiType(type: WidgetType): boolean {
  return KPI_TYPES.includes(type);
}

// ---------- Validação ----------

const periodSchema = z.union([z.literal(7), z.literal(30), z.literal(90), z.literal(365)]);

export const widgetConfigSchema = z.object({
  period: periodSchema.optional(),
  limit: z.number().int().min(1).max(100).optional(),
  filters: voterFiltersSchema.optional(),
  text: z.string().max(MAX_NOTE_LENGTH, `O texto pode ter no máximo ${MAX_NOTE_LENGTH} caracteres`).optional(),
});

export const dashboardWidgetSchema = z.object({
  id: z
    .string()
    .min(1)
    .max(40)
    .regex(/^[A-Za-z0-9_-]+$/, "Identificador de widget inválido"),
  type: z.enum(WIDGET_TYPES),
  title: z
    .string()
    .trim()
    .max(MAX_WIDGET_TITLE, `O título pode ter no máximo ${MAX_WIDGET_TITLE} caracteres`)
    .optional()
    .nullable()
    .transform((v) => (v ? v : undefined)),
  size: z.enum(WIDGET_SIZES),
  config: widgetConfigSchema.optional().default({}),
});

/** Lista de widgets de um dashboard (máx. 30, ids únicos). Normaliza cada widget. */
export const dashboardWidgetsSchema = z
  .array(dashboardWidgetSchema)
  .max(MAX_WIDGETS, `Um dashboard pode ter no máximo ${MAX_WIDGETS} widgets`)
  .superRefine((list, ctx) => {
    const seen = new Set<string>();
    for (const w of list) {
      if (seen.has(w.id)) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, message: "Há widgets repetidos" });
        return;
      }
      seen.add(w.id);
    }
  })
  .transform((list) => list.map((w) => sanitizeWidget(w as DashboardWidget)));

/** Mantém só as opções suportadas pelo tipo e limita os valores ao intervalo permitido */
export function sanitizeWidget(widget: DashboardWidget): DashboardWidget {
  const def = WIDGET_CATALOG[widget.type];
  const config: WidgetConfig = {};
  const src = widget.config ?? {};
  if (def.options.period && src.period !== undefined) config.period = src.period;
  if (def.options.limit && src.limit !== undefined) {
    config.limit = Math.min(def.options.limit.max, Math.max(def.options.limit.min, Math.round(src.limit)));
  }
  if (def.options.filters && src.filters) {
    const cleaned = cleanVoterFilters(src.filters);
    if (Object.keys(cleaned).length) config.filters = cleaned;
  }
  if (def.options.text && src.text !== undefined) config.text = src.text.slice(0, MAX_NOTE_LENGTH);
  const out: DashboardWidget = { id: widget.id, type: widget.type, size: widget.size, config };
  const title = widget.title?.trim();
  if (title) out.title = title.slice(0, MAX_WIDGET_TITLE);
  return out;
}

/** Lê o JSON salvo no banco de forma tolerante: descarta widgets inválidos em vez de falhar */
export function parseDashboardWidgets(value: unknown): DashboardWidget[] {
  if (!Array.isArray(value)) return [];
  const out: DashboardWidget[] = [];
  const seen = new Set<string>();
  for (const item of value) {
    const parsed = dashboardWidgetSchema.safeParse(item);
    if (!parsed.success || seen.has(parsed.data.id)) continue;
    seen.add(parsed.data.id);
    out.push(sanitizeWidget(parsed.data as DashboardWidget));
    if (out.length >= MAX_WIDGETS) break;
  }
  return out;
}

export function effectivePeriod(widget: Pick<DashboardWidget, "config">): WidgetPeriod {
  return widget.config.period ?? DEFAULT_WIDGET_PERIOD;
}

export function effectiveLimit(widget: Pick<DashboardWidget, "type" | "config">): number {
  const opt = WIDGET_CATALOG[widget.type].options.limit;
  if (!opt) return 0;
  const v = widget.config.limit ?? opt.default;
  return Math.min(opt.max, Math.max(opt.min, v));
}

export function widgetTitle(widget: Pick<DashboardWidget, "type" | "title">): string {
  return widget.title?.trim() || WIDGET_CATALOG[widget.type].label;
}

function stableStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v !== undefined)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${stableStringify(v)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

/**
 * Chave dos dados de um widget: dois widgets com a mesma chave mostram os mesmos dados.
 * Título, tamanho e texto não alteram os dados (não entram na chave).
 */
export function widgetDataKey(widget: DashboardWidget): string {
  const def = WIDGET_CATALOG[widget.type];
  const parts: Record<string, unknown> = { type: widget.type };
  if (def.options.period) parts.period = effectivePeriod(widget);
  if (def.options.limit) parts.limit = effectiveLimit(widget);
  if (def.options.filters && widget.config.filters) {
    const cleaned = cleanVoterFilters(widget.config.filters);
    const normalized: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(cleaned)) normalized[k] = Array.isArray(v) ? [...v].map(String).sort() : v;
    if (Object.keys(normalized).length) parts.filters = normalized;
  }
  return stableStringify(parts);
}

/** Identificador curto e aleatório para um widget novo */
export function newWidgetId(): string {
  return `w${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

/** Widget novo com tamanho e opções padrão do catálogo */
export function createWidget(type: WidgetType, id: string = newWidgetId()): DashboardWidget {
  const def = WIDGET_CATALOG[type];
  const config: WidgetConfig = {};
  if (def.options.period) config.period = DEFAULT_WIDGET_PERIOD;
  if (def.options.limit) config.limit = def.options.limit.default;
  if (def.options.text) config.text = "";
  return { id, type, size: def.defaultSize, config };
}

// ---------- Dados devolvidos por POST /api/painel/dashboard/data ----------

export interface CategoryCount {
  key: string;
  label: string;
  count: number;
}

export interface PeriodComparison {
  current: number;
  previous: number;
  /** Variação percentual; null quando o período anterior é zero */
  deltaPct: number | null;
  trend: "up" | "down" | "flat";
}

export interface KpiTotalData {
  type: "kpi_total";
  total: number;
  last7: number;
}
export interface KpiTodayData {
  type: "kpi_today";
  today: number;
  yesterday: number;
}
export interface KpiPeriodData {
  type: "kpi_period";
  period: WidgetPeriod;
  comparison: PeriodComparison;
}
export interface KpiGoalData {
  type: "kpi_goal";
  total: number;
  goal: number | null;
  pct: number | null;
  /** campaign = meta da campanha (ADMIN); team = soma das metas individuais da equipe visível */
  source: "campaign" | "team";
  membersWithGoal: number;
}
export interface KpiMessageableData {
  type: "kpi_messageable";
  messageable: number;
  total: number;
  pct: number | null;
}
export interface KpiTeamData {
  type: "kpi_team";
  period: WidgetPeriod;
  active: number;
  contributing: number;
  pct: number | null;
}

export interface MemberRankingRow {
  id: string;
  name: string;
  role: CampaignRole;
  active: boolean;
  coordinatorName: string | null;
  total: number;
  inPeriod: number;
  goal: number | null;
  goalPct: number | null;
  /** ISO */
  lastAt: string | null;
}
export interface RankingMembersData {
  type: "ranking_members";
  period: WidgetPeriod;
  rows: MemberRankingRow[];
  total: number;
  periodTotal: number;
  /** Membros que cadastraram no período */
  contributing: number;
}

export interface CoordinatorRankingRow {
  id: string;
  name: string;
  active: boolean;
  cabos: number;
  /** Cadastros feitos pelo próprio coordenador */
  own: number;
  total: number;
  inPeriod: number;
  goal: number | null;
  goalPct: number | null;
}
export interface RankingCoordinatorsData {
  type: "ranking_coordinators";
  period: WidgetPeriod;
  /** false para quem não tem coordenadores no escopo (cabo eleitoral) */
  applicable: boolean;
  rows: CoordinatorRankingRow[];
  /** Cadastros fora de qualquer rede de coordenador (administração e cabos sem coordenador) */
  others: { total: number; inPeriod: number } | null;
}

export interface TimelinePoint {
  /** yyyy-mm-dd (dia em America/Sao_Paulo) */
  date: string;
  count: number;
}
export interface TimelineData {
  type: "timeline";
  period: WidgetPeriod;
  points: TimelinePoint[];
  total: number;
  previousTotal: number;
}

export interface TopListData {
  type: "by_neighborhood" | "by_city";
  rows: CategoryCount[];
  /** Soma das categorias fora do top N */
  others: number;
  othersCategories: number;
  /** Eleitores sem bairro/cidade informado */
  missing: number;
  total: number;
}

export interface DistributionData {
  type: "by_gender" | "by_support" | "by_source" | "by_age";
  rows: CategoryCount[];
  total: number;
}

export interface RecentVoterRow {
  id: string;
  name: string;
  neighborhood: string | null;
  city: string | null;
  registeredBy: string;
  /** ISO */
  createdAt: string;
}
export interface RecentVotersData {
  type: "recent_voters";
  locked: boolean;
  rows: RecentVoterRow[];
}

export interface BroadcastSummaryRow {
  id: string;
  name: string;
  status: BroadcastStatus;
  totalRecipients: number;
  sentCount: number;
  deliveredCount: number;
  readCount: number;
  failedCount: number;
  /** ISO */
  createdAt: string;
}
export interface BroadcastsData {
  type: "broadcasts";
  locked: boolean;
  period: WidgetPeriod;
  /** campaign = todos os disparos; own = apenas os criados pelo usuário */
  scope: "campaign" | "own";
  sent: number;
  delivered: number;
  read: number;
  failed: number;
  pending: number;
  deliveryRate: number | null;
  readRate: number | null;
  recent: BroadcastSummaryRow[];
}

export interface GoalProgressRow {
  id: string;
  name: string;
  role: CampaignRole;
  total: number;
  goal: number;
  pct: number;
}
export interface GoalsProgressData {
  type: "goals_progress";
  rows: GoalProgressRow[];
  /** Membros ativos sem meta individual definida */
  withoutGoal: number;
}

export interface NoteData {
  type: "note";
}

export type WidgetData =
  | KpiTotalData
  | KpiTodayData
  | KpiPeriodData
  | KpiGoalData
  | KpiMessageableData
  | KpiTeamData
  | RankingMembersData
  | RankingCoordinatorsData
  | TimelineData
  | TopListData
  | DistributionData
  | RecentVotersData
  | BroadcastsData
  | GoalsProgressData
  | NoteData;

export type WidgetResult = WidgetData | { error: string };

/** Corpo da resposta: { [widgetId]: dados | { error } } */
export type DashboardDataResponse = Record<string, WidgetResult>;

export function isWidgetError(result: WidgetResult | undefined): result is { error: string } {
  return !!result && "error" in result;
}

/** O que o usuário pode ver (calculado no servidor a partir das permissões) */
export interface DashboardCapabilities {
  canViewVoters: boolean;
  canViewBroadcasts: boolean;
  canViewTeam: boolean;
}

/** Paleta categórica dos gráficos */
export const CHART_PALETTE = ["#4f46e5", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#64748b"] as const;
