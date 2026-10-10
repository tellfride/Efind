// Regras de acesso aos dashboards (puras — testadas em tests/dashboard*.test.ts).
//  - Ver: mesma campanha + permissão dashboard.view + (compartilhado OU dono).
//  - Editar/excluir: ADMIN edita/exclui qualquer dashboard visível; demais usuários só os próprios
//    dashboards não compartilhados, com dashboard.edit / dashboard.delete.
//  - Padrão da campanha = shared && isDefault (exatamente um, definido pelo ADMIN).
//  - "Meu padrão" = dashboard próprio, não compartilhado, com isDefault (um por dono).
import { can, type PermissionSet } from "@/lib/permissions";
import type { CampaignRole } from "@/lib/constants";

export interface DashboardRuleUser {
  id: string;
  role: CampaignRole;
  campaignId: string;
  permissions: PermissionSet;
}

export interface DashboardRuleTarget {
  campaignId: string;
  ownerId: string | null;
  shared: boolean;
  isDefault: boolean;
}

export function isDashboardVisible(user: DashboardRuleUser, d: DashboardRuleTarget): boolean {
  if (d.campaignId !== user.campaignId) return false;
  if (!can(user.permissions, "dashboard", "view")) return false;
  return d.shared || d.ownerId === user.id;
}

export function canEditDashboard(user: DashboardRuleUser, d: DashboardRuleTarget): boolean {
  if (!isDashboardVisible(user, d)) return false;
  if (user.role === "ADMIN") return true;
  return d.ownerId === user.id && !d.shared && can(user.permissions, "dashboard", "edit");
}

export function canDeleteDashboard(user: DashboardRuleUser, d: DashboardRuleTarget): boolean {
  if (!isDashboardVisible(user, d)) return false;
  if (user.role === "ADMIN") return true;
  return d.ownerId === user.id && !d.shared && can(user.permissions, "dashboard", "delete");
}

export function canDuplicateDashboard(user: DashboardRuleUser, d: DashboardRuleTarget): boolean {
  return isDashboardVisible(user, d) && can(user.permissions, "dashboard", "create");
}

/** "Meu padrão" só vale para dashboards próprios e não compartilhados */
export function canSetMyDefault(user: DashboardRuleUser, d: DashboardRuleTarget): boolean {
  return isDashboardVisible(user, d) && d.ownerId === user.id && !d.shared;
}

export function isCampaignDefault(d: Pick<DashboardRuleTarget, "shared" | "isDefault">): boolean {
  return d.shared && d.isDefault;
}

export function isPersonalDefault(d: Pick<DashboardRuleTarget, "shared" | "isDefault" | "ownerId">, userId: string): boolean {
  return !d.shared && d.isDefault && d.ownerId === userId;
}

/** Dashboard aberto em /painel: meu padrão → padrão da campanha → primeiro visível */
export function pickHomeDashboard<T extends DashboardRuleTarget>(visible: T[], userId: string): T | null {
  return (
    visible.find((d) => isPersonalDefault(d, userId)) ??
    visible.find((d) => isCampaignDefault(d)) ??
    visible[0] ??
    null
  );
}

/** Ordem da lista: padrão da campanha, meu padrão, compartilhados, próprios — e por nome */
export function sortDashboards<T extends DashboardRuleTarget & { name: string }>(list: T[], userId: string): T[] {
  const weight = (d: T) => (isCampaignDefault(d) ? 0 : isPersonalDefault(d, userId) ? 1 : d.shared ? 2 : 3);
  return [...list].sort((a, b) => weight(a) - weight(b) || a.name.localeCompare(b.name, "pt-BR"));
}

export interface SharingInput {
  shared: boolean;
  campaignDefault: boolean;
}

/**
 * Novo estado de compartilhamento ao salvar.
 * Só o ADMIN altera "compartilhado" e "padrão da campanha"; para os demais o estado atual é mantido.
 * Ao deixar de compartilhar um dashboard sem dono, o ADMIN passa a ser o dono (senão ninguém o veria).
 */
export function resolveSharing(
  user: Pick<DashboardRuleUser, "id" | "role">,
  current: Pick<DashboardRuleTarget, "ownerId" | "shared" | "isDefault">,
  input: SharingInput,
): { shared: boolean; isDefault: boolean; ownerId: string | null } {
  if (user.role !== "ADMIN") return { shared: current.shared, isDefault: current.isDefault, ownerId: current.ownerId };
  const campaignDefault = input.campaignDefault;
  const shared = campaignDefault || input.shared;
  if (shared) return { shared: true, isDefault: campaignDefault, ownerId: current.ownerId };
  // Deixou de ser compartilhado: perde o "padrão da campanha", mas mantém "meu padrão" se já era pessoal
  const keepPersonal = !current.shared && current.isDefault;
  return { shared: false, isDefault: keepPersonal, ownerId: current.ownerId ?? user.id };
}
