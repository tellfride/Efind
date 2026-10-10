// Consultas da trilha de auditoria da campanha (servidor).
// Sempre restritas à campanha do usuário; quem não é ADMIN vê apenas as ações da própria rede.
import { prisma } from "@/lib/db";
import { AUDIT_ACTIONS } from "@/lib/audit";
import type { CampaignUser } from "@/lib/auth";
import { ROLE_LABELS, type Role } from "@/lib/constants";
import { getScopeUserIds, teamScopeWhere } from "@/server/access";
import { formatDateTime } from "@/lib/utils";
import {
  AUDIT_EXPORT_LIMIT,
  AUDIT_PAGE_SIZE,
  auditActionLabel,
  auditEntityLabel,
  buildAuditWhere,
  formatAuditDetails,
  groupAuditActions,
  parseAuditFilters,
  type AuditActionGroup,
  type AuditFilters,
} from "./audit-filters";

/** Ações registradas por este módulo que ainda não constam em AUDIT_ACTIONS */
const EXTRA_AUDIT_LABELS: Record<string, string> = {
  "audit.export": "Auditoria exportada",
};

export const AUDIT_LABELS: Readonly<Record<string, string>> = { ...AUDIT_ACTIONS, ...EXTRA_AUDIT_LABELS };

export function labelForAction(action: string): string {
  return auditActionLabel(action, AUDIT_LABELS);
}

export interface AuditUserOption {
  id: string;
  name: string;
  roleLabel: string;
  active: boolean;
}

export interface AuditFilterOptions {
  users: AuditUserOption[];
  actionGroups: AuditActionGroup[];
  allowedActions: string[];
  /** true quando o usuário vê apenas a própria rede */
  scoped: boolean;
}

export interface AuditContext {
  scopeUserIds: string[] | null;
  options: AuditFilterOptions;
}

/** Escopo + opções de filtro (usuários da rede e ações conhecidas/registradas) */
export async function getAuditContext(user: CampaignUser): Promise<AuditContext> {
  const scopeUserIds = await getScopeUserIds(user);
  const baseWhere = buildAuditWhere(user.campaignId, {}, scopeUserIds);

  const [team, present] = await Promise.all([
    prisma.user.findMany({
      where: teamScopeWhere(user),
      select: { id: true, name: true, role: true, active: true },
      orderBy: { name: "asc" },
    }),
    prisma.auditLog.groupBy({ by: ["action"], where: baseWhere }),
  ]);

  const allowedActions = Array.from(new Set([...Object.keys(AUDIT_LABELS), ...present.map((p) => p.action)]));
  return {
    scopeUserIds,
    options: {
      users: team.map((u) => ({
        id: u.id,
        name: u.name,
        roleLabel: ROLE_LABELS[u.role as Role] ?? u.role,
        active: u.active,
      })),
      actionGroups: groupAuditActions(allowedActions, AUDIT_LABELS),
      allowedActions,
      scoped: scopeUserIds !== null,
    },
  };
}

export function parseFiltersFor(
  context: AuditContext,
  sp: URLSearchParams | Record<string, string | string[] | undefined>,
): AuditFilters {
  return parseAuditFilters(sp, {
    allowedUserIds: context.options.users.map((u) => u.id),
    allowedActions: context.options.allowedActions,
  });
}

export interface AuditRow {
  id: string;
  createdAt: Date;
  action: string;
  actionLabel: string;
  userName: string | null;
  userRoleLabel: string | null;
  /** Ação feita pelo suporte da plataforma (super admin) */
  byPlatform: boolean;
  entity: string | null;
  entityId: string | null;
  ip: string | null;
  details: string | null;
}

export async function listAuditLogs(
  user: CampaignUser,
  context: AuditContext,
  filters: AuditFilters,
  page: number,
): Promise<{ rows: AuditRow[]; total: number; page: number }> {
  const where = buildAuditWhere(user.campaignId, filters, context.scopeUserIds);
  const total = await prisma.auditLog.count({ where });
  const pages = Math.max(1, Math.ceil(total / AUDIT_PAGE_SIZE));
  const current = Math.min(page, pages);
  const logs = await prisma.auditLog.findMany({
    where,
    orderBy: [{ createdAt: "desc" }, { id: "desc" }],
    skip: (current - 1) * AUDIT_PAGE_SIZE,
    take: AUDIT_PAGE_SIZE,
    include: { user: { select: { name: true, role: true } } },
  });
  return { rows: logs.map(toRow), total, page: current };
}

function toRow(log: {
  id: string;
  createdAt: Date;
  action: string;
  entity: string | null;
  entityId: string | null;
  ip: string | null;
  details: unknown;
  user: { name: string; role: string } | null;
}): AuditRow {
  return {
    id: log.id,
    createdAt: log.createdAt,
    action: log.action,
    actionLabel: labelForAction(log.action),
    userName: log.user?.name ?? null,
    userRoleLabel: log.user ? (ROLE_LABELS[log.user.role as Role] ?? log.user.role) : null,
    byPlatform: log.user?.role === "SUPER_ADMIN",
    entity: auditEntityLabel(log.entity),
    entityId: log.entityId,
    ip: log.ip,
    details: formatAuditDetails(log.details),
  };
}

export const AUDIT_CSV_COLUMNS = [
  { key: "dataHora", label: "Data/hora (Brasília)" },
  { key: "usuario", label: "Usuário" },
  { key: "papel", label: "Papel" },
  { key: "acao", label: "Ação" },
  { key: "codigoAcao", label: "Código da ação" },
  { key: "entidade", label: "Entidade" },
  { key: "idEntidade", label: "ID da entidade" },
  { key: "ip", label: "IP" },
  { key: "detalhes", label: "Detalhes (JSON)" },
];

/** Linhas para o CSV (limitadas a AUDIT_EXPORT_LIMIT) */
export async function exportAuditRows(
  user: CampaignUser,
  context: AuditContext,
  filters: AuditFilters,
): Promise<{ rows: Record<string, unknown>[]; truncated: boolean }> {
  const where = buildAuditWhere(user.campaignId, filters, context.scopeUserIds);
  const logs = await prisma.auditLog.findMany({
    where,
    orderBy: [{ createdAt: "desc" }, { id: "desc" }],
    take: AUDIT_EXPORT_LIMIT + 1,
    include: { user: { select: { name: true, role: true } } },
  });
  const truncated = logs.length > AUDIT_EXPORT_LIMIT;
  const rows = logs.slice(0, AUDIT_EXPORT_LIMIT).map((log) => {
    const r = toRow(log);
    return {
      dataHora: formatDateTime(r.createdAt),
      usuario: r.byPlatform ? `${r.userName ?? ""} (suporte E-Find)` : (r.userName ?? "Sistema / eleitor"),
      papel: r.userRoleLabel ?? "",
      acao: r.actionLabel,
      codigoAcao: r.action,
      entidade: r.entity ?? "",
      idEntidade: r.entityId ?? "",
      ip: r.ip ?? "",
      detalhes: log.details === null || log.details === undefined ? "" : JSON.stringify(log.details),
    };
  });
  return { rows, truncated };
}
