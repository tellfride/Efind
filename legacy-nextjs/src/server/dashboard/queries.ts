// Leituras de dashboards para as páginas (sempre limitadas à campanha e à visibilidade do usuário).
import { prisma, type Prisma } from "@/lib/db";
import type { CampaignUser } from "@/lib/auth";
import { can } from "@/lib/permissions";
import { parseDashboardWidgets, type DashboardCapabilities, type DashboardWidget } from "@/lib/dashboard-types";
import {
  canDeleteDashboard,
  canDuplicateDashboard,
  canEditDashboard,
  canSetMyDefault,
  isCampaignDefault,
  isPersonalDefault,
  sortDashboards,
} from "./rules";

const dashboardSelect = {
  id: true,
  campaignId: true,
  ownerId: true,
  name: true,
  description: true,
  shared: true,
  isDefault: true,
  widgets: true,
  updatedAt: true,
  owner: { select: { name: true } },
} satisfies Prisma.DashboardSelect;

export interface DashboardSummary {
  id: string;
  campaignId: string;
  ownerId: string | null;
  ownerName: string | null;
  name: string;
  description: string | null;
  shared: boolean;
  isDefault: boolean;
  widgets: DashboardWidget[];
  updatedAt: Date;
  isCampaignDefault: boolean;
  isMyDefault: boolean;
  isMine: boolean;
  canEdit: boolean;
  canDelete: boolean;
  canDuplicate: boolean;
  canSetMyDefault: boolean;
}

type Row = Prisma.DashboardGetPayload<{ select: typeof dashboardSelect }>;

function toSummary(user: CampaignUser, d: Row): DashboardSummary {
  return {
    id: d.id,
    campaignId: d.campaignId,
    ownerId: d.ownerId,
    ownerName: d.owner?.name ?? null,
    name: d.name,
    description: d.description,
    shared: d.shared,
    isDefault: d.isDefault,
    widgets: parseDashboardWidgets(d.widgets),
    updatedAt: d.updatedAt,
    isCampaignDefault: isCampaignDefault(d),
    isMyDefault: isPersonalDefault(d, user.id),
    isMine: d.ownerId === user.id,
    canEdit: canEditDashboard(user, d),
    canDelete: canDeleteDashboard(user, d),
    canDuplicate: canDuplicateDashboard(user, d),
    canSetMyDefault: canSetMyDefault(user, d),
  };
}

/** Dashboards visíveis ao usuário (compartilhados + próprios), já ordenados */
export async function listVisibleDashboards(user: CampaignUser): Promise<DashboardSummary[]> {
  if (!can(user.permissions, "dashboard", "view")) return [];
  const rows = await prisma.dashboard.findMany({
    where: { campaignId: user.campaignId, OR: [{ shared: true }, { ownerId: user.id }] },
    select: dashboardSelect,
    orderBy: { createdAt: "asc" },
    take: 300,
  });
  return sortDashboards(
    rows.map((r) => toSummary(user, r)),
    user.id,
  );
}

/** Um dashboard visível ao usuário (ou null) */
export async function getVisibleDashboard(user: CampaignUser, id: string): Promise<DashboardSummary | null> {
  if (!id || id.length > 64 || !can(user.permissions, "dashboard", "view")) return null;
  const row = await prisma.dashboard.findFirst({
    where: { id, campaignId: user.campaignId, OR: [{ shared: true }, { ownerId: user.id }] },
    select: dashboardSelect,
  });
  return row ? toSummary(user, row) : null;
}

export async function countCampaignDashboards(campaignId: string): Promise<number> {
  return prisma.dashboard.count({ where: { campaignId } });
}

export function dashboardCapabilities(user: CampaignUser): DashboardCapabilities {
  return {
    canViewVoters: can(user.permissions, "eleitores", "view"),
    canViewBroadcasts: can(user.permissions, "disparos", "view"),
    canViewTeam: can(user.permissions, "equipe", "view"),
  };
}
