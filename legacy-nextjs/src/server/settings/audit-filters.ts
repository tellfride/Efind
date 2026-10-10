// Filtros da trilha de auditoria (puro: sem banco, sem next/*) — testado em tests/settings*.test.ts.
import type { Prisma } from "@prisma/client";

export const AUDIT_PAGE_SIZE = 50;
/** Limite de linhas por exportação CSV */
export const AUDIT_EXPORT_LIMIT = 50_000;

export interface AuditFilters {
  userId?: string;
  action?: string;
  /** AAAA-MM-DD (fuso de Brasília) */
  from?: string;
  to?: string;
}

type SearchParamsInput = URLSearchParams | Record<string, string | string[] | undefined>;

function first(sp: SearchParamsInput, key: string): string | undefined {
  if (sp instanceof URLSearchParams) return sp.get(key) ?? undefined;
  const v = sp[key];
  return Array.isArray(v) ? v[0] : v;
}

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const ID_REGEX = /^[A-Za-z0-9_-]{8,64}$/;
const ACTION_REGEX = /^[a-z0-9_]+(\.[a-z0-9_]+)*$/;

/** Data AAAA-MM-DD válida no calendário */
export function isValidIsoDate(value: string | undefined | null): value is string {
  if (!value) return false;
  const m = ISO_DATE.exec(value);
  if (!m) return false;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  if (y < 2000 || y > 2100) return false;
  const date = new Date(Date.UTC(y, mo - 1, d));
  return date.getUTCFullYear() === y && date.getUTCMonth() === mo - 1 && date.getUTCDate() === d;
}

/**
 * Lê os filtros da URL com segurança. Valores fora das listas permitidas são descartados
 * (nunca ampliam o escopo: o where final sempre inclui a campanha e a rede do usuário).
 */
export function parseAuditFilters(
  sp: SearchParamsInput,
  opts: { allowedUserIds?: readonly string[]; allowedActions?: readonly string[] } = {},
): AuditFilters {
  const out: AuditFilters = {};

  const userId = first(sp, "user")?.trim();
  if (userId && ID_REGEX.test(userId) && (!opts.allowedUserIds || opts.allowedUserIds.includes(userId))) {
    out.userId = userId;
  }

  const action = first(sp, "action")?.trim();
  if (action && ACTION_REGEX.test(action) && (!opts.allowedActions || opts.allowedActions.includes(action))) {
    out.action = action;
  }

  let from = first(sp, "from")?.trim();
  let to = first(sp, "to")?.trim();
  if (!isValidIsoDate(from)) from = undefined;
  if (!isValidIsoDate(to)) to = undefined;
  if (from && to && from > to) [from, to] = [to, from];
  if (from) out.from = from;
  if (to) out.to = to;

  return out;
}

/** Filtros → parâmetros de URL (paginação e exportação) */
export function auditFiltersToSearchParams(filters: AuditFilters): URLSearchParams {
  const sp = new URLSearchParams();
  if (filters.userId) sp.set("user", filters.userId);
  if (filters.action) sp.set("action", filters.action);
  if (filters.from) sp.set("from", filters.from);
  if (filters.to) sp.set("to", filters.to);
  return sp;
}

export function hasAuditFilters(filters: AuditFilters): boolean {
  return !!(filters.userId || filters.action || filters.from || filters.to);
}

export function startOfDayBrt(iso: string): Date {
  return new Date(`${iso}T00:00:00.000-03:00`);
}

export function endOfDayBrt(iso: string): Date {
  return new Date(`${iso}T23:59:59.999-03:00`);
}

/**
 * where da auditoria: SEMPRE a campanha do usuário; scopeUserIds = null para a campanha inteira (ADMIN),
 * ou a lista de usuários da rede (coordenador/cabo veem apenas as ações da própria rede).
 */
export function buildAuditWhere(
  campaignId: string,
  filters: AuditFilters,
  scopeUserIds: readonly string[] | null,
): Prisma.AuditLogWhereInput {
  const and: Prisma.AuditLogWhereInput[] = [{ campaignId }];
  if (scopeUserIds) and.push({ userId: { in: [...scopeUserIds] } });
  if (filters.userId) and.push({ userId: filters.userId });
  if (filters.action) and.push({ action: filters.action });
  if (filters.from || filters.to) {
    const createdAt: Prisma.DateTimeFilter = {};
    if (filters.from) createdAt.gte = startOfDayBrt(filters.from);
    if (filters.to) createdAt.lte = endOfDayBrt(filters.to);
    and.push({ createdAt });
  }
  return { AND: and };
}

// ---------- Rótulos e agrupamento das ações ----------

export const AUDIT_CATEGORY_LABELS: Record<string, string> = {
  auth: "Acesso",
  campaign: "Campanha",
  settings: "Configurações",
  user: "Equipe",
  permissions: "Equipe",
  voter: "Eleitores",
  template: "Modelos de mensagem",
  broadcast: "Disparos",
  whatsapp: "WhatsApp",
  dashboard: "Dashboards",
  audit: "Auditoria",
};

export function auditCategory(action: string): string {
  return AUDIT_CATEGORY_LABELS[action.split(".")[0]] ?? "Outras";
}

/** Rótulo de uma ação: tabela conhecida → "entidade.verbo" legível */
export function auditActionLabel(action: string, labels: Readonly<Record<string, string>>): string {
  if (labels[action]) return labels[action];
  const verb = action.split(".").slice(1).join(" ").replace(/_/g, " ").trim();
  const category = auditCategory(action);
  return verb ? `${category}: ${verb}` : action;
}

export interface AuditActionGroup {
  label: string;
  options: { value: string; label: string }[];
}

/** Agrupa ações por categoria (para <optgroup>), sem repetição, ordenadas por rótulo */
export function groupAuditActions(actions: readonly string[], labels: Readonly<Record<string, string>>): AuditActionGroup[] {
  const groups = new Map<string, AuditActionGroup>();
  for (const action of Array.from(new Set(actions))) {
    const category = auditCategory(action);
    if (!groups.has(category)) groups.set(category, { label: category, options: [] });
    groups.get(category)!.options.push({ value: action, label: auditActionLabel(action, labels) });
  }
  const list = Array.from(groups.values());
  for (const g of list) g.options.sort((a, b) => a.label.localeCompare(b.label, "pt-BR"));
  return list.sort((a, b) => {
    if (a.label === "Outras") return 1;
    if (b.label === "Outras") return -1;
    return a.label.localeCompare(b.label, "pt-BR");
  });
}

/** Rótulo da entidade afetada */
const ENTITY_LABELS: Record<string, string> = {
  voter: "Eleitor",
  user: "Usuário",
  campaign: "Campanha",
  messagetemplate: "Modelo de mensagem",
  template: "Modelo de mensagem",
  broadcast: "Disparo",
  whatsappconnection: "Conexão de WhatsApp",
  connection: "Conexão de WhatsApp",
  dashboard: "Dashboard",
  rolepermission: "Permissões",
  userpermission: "Permissões",
  permission: "Permissões",
  permissions: "Permissões",
  auditlog: "Auditoria",
};

export function auditEntityLabel(entity: string | null | undefined): string | null {
  if (!entity) return null;
  return ENTITY_LABELS[entity.replace(/[^a-z]/gi, "").toLowerCase()] ?? entity;
}

/** JSON legível dos detalhes (null quando não há detalhes) */
export function formatAuditDetails(details: unknown): string | null {
  if (details === null || details === undefined) return null;
  if (typeof details === "object" && !Array.isArray(details) && Object.keys(details as object).length === 0) return null;
  try {
    return JSON.stringify(details, null, 2);
  } catch {
    return String(details);
  }
}

/** Nome do arquivo CSV exportado */
export function auditExportFilename(filters: AuditFilters, now = new Date()): string {
  const stamp = now.toLocaleDateString("sv-SE", { timeZone: "America/Sao_Paulo" }); // AAAA-MM-DD
  const range = filters.from || filters.to ? `_${filters.from ?? "inicio"}_a_${filters.to ?? "hoje"}` : "";
  return `auditoria_${stamp}${range}.csv`;
}
