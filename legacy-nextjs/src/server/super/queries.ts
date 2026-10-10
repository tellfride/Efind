// Leituras do super admin (Server Components). Somente contagens agregadas de eleitores:
// o super admin nunca recebe nome, telefone ou endereço de eleitores.
import { prisma, type Prisma } from "@/lib/db";
import { MESSAGEABLE_WHERE } from "@/server/access";
import { CAMPAIGN_ROLES, type CampaignRole } from "@/lib/constants";
import { auditDateRange, PLATFORM_SCOPE, sanitizeAuditDetails, type AuditFilterParams, type CampaignListParams } from "./filters";

const DAY_MS = 86_400_000;
const daysAgo = (n: number) => new Date(Date.now() - n * DAY_MS);

export const CAMPAIGN_LIST_SELECT = {
  id: true,
  slug: true,
  candidateName: true,
  ballotName: true,
  ballotNumber: true,
  party: true,
  office: true,
  city: true,
  state: true,
  status: true,
  primaryColor: true,
  createdAt: true,
  _count: { select: { users: true, voters: true } },
} satisfies Prisma.CampaignSelect;

export type CampaignListItem = Prisma.CampaignGetPayload<{ select: typeof CAMPAIGN_LIST_SELECT }>;

/** Indicadores da plataforma + campanhas mais recentes */
export async function getPlatformOverview(recentLimit = 8) {
  const [active, suspended, campaignUsers, voters, votersLast7, recent, totalCampaigns] = await Promise.all([
    prisma.campaign.count({ where: { status: "ACTIVE" } }),
    prisma.campaign.count({ where: { status: "SUSPENDED" } }),
    prisma.user.count({ where: { campaignId: { not: null }, role: { not: "SUPER_ADMIN" } } }),
    prisma.voter.count(),
    prisma.voter.count({ where: { createdAt: { gte: daysAgo(7) } } }),
    prisma.campaign.findMany({ select: CAMPAIGN_LIST_SELECT, orderBy: { createdAt: "desc" }, take: recentLimit }),
    prisma.campaign.count(),
  ]);
  return { active, suspended, campaignUsers, voters, votersLast7, recent, totalCampaigns };
}

export async function listCampaigns(params: CampaignListParams, pageSize = 25) {
  const and: Prisma.CampaignWhereInput[] = [];
  if (params.status) and.push({ status: params.status });
  if (params.q) {
    const q = params.q;
    and.push({
      OR: [
        { candidateName: { contains: q } },
        { ballotName: { contains: q } },
        { ballotNumber: { contains: q } },
        { party: { contains: q } },
        { city: { contains: q } },
        { slug: { contains: q.toLowerCase() } },
      ],
    });
  }
  const where: Prisma.CampaignWhereInput = and.length ? { AND: and } : {};
  const [items, total] = await Promise.all([
    prisma.campaign.findMany({
      where,
      select: CAMPAIGN_LIST_SELECT,
      orderBy: { createdAt: "desc" },
      skip: (params.page - 1) * pageSize,
      take: pageSize,
    }),
    prisma.campaign.count({ where }),
  ]);
  return { items, total };
}

/** Dados cadastrais da campanha (sem dados de eleitores) */
export async function getCampaignById(id: string) {
  return prisma.campaign.findUnique({
    where: { id },
    select: {
      id: true,
      slug: true,
      candidateName: true,
      ballotName: true,
      ballotNumber: true,
      party: true,
      office: true,
      city: true,
      state: true,
      electionYear: true,
      primaryColor: true,
      voterGoal: true,
      status: true,
      createdAt: true,
      updatedAt: true,
    },
  });
}

export type CampaignDetail = NonNullable<Awaited<ReturnType<typeof getCampaignById>>>;

export const ACCOUNT_SELECT = {
  id: true,
  name: true,
  email: true,
  phone: true,
  active: true,
  lastLoginAt: true,
  createdAt: true,
} satisfies Prisma.UserSelect;

export type AccountRow = Prisma.UserGetPayload<{ select: typeof ACCOUNT_SELECT }>;

export async function getCampaignAdmins(campaignId: string): Promise<AccountRow[]> {
  return prisma.user.findMany({
    where: { campaignId, role: "ADMIN" },
    select: ACCOUNT_SELECT,
    orderBy: [{ active: "desc" }, { createdAt: "asc" }],
  });
}

export async function listSuperUsers(): Promise<AccountRow[]> {
  return prisma.user.findMany({
    where: { role: "SUPER_ADMIN" },
    select: ACCOUNT_SELECT,
    orderBy: [{ active: "desc" }, { createdAt: "asc" }],
  });
}

/** Uso da campanha — apenas contagens agregadas */
export async function getCampaignUsage(campaignId: string) {
  const SENT_STATUSES = ["SENT", "DELIVERED", "READ"];
  const [
    usersByRole,
    voters,
    voters7,
    voters30,
    messageable,
    optedOut,
    geolocated,
    connections,
    connectedConnections,
    templates,
    dashboards,
    broadcasts,
    broadcastsByStatus,
    messagesSent,
    messagesFailed,
    lastLogin,
  ] = await Promise.all([
    prisma.user.groupBy({ by: ["role", "active"], where: { campaignId }, _count: { _all: true } }),
    prisma.voter.count({ where: { campaignId } }),
    prisma.voter.count({ where: { campaignId, createdAt: { gte: daysAgo(7) } } }),
    prisma.voter.count({ where: { campaignId, createdAt: { gte: daysAgo(30) } } }),
    prisma.voter.count({ where: { AND: [{ campaignId }, MESSAGEABLE_WHERE] } }),
    prisma.voter.count({ where: { campaignId, optOutAt: { not: null } } }),
    prisma.voter.count({ where: { campaignId, latitude: { not: null }, longitude: { not: null } } }),
    prisma.whatsAppConnection.count({ where: { campaignId } }),
    prisma.whatsAppConnection.count({ where: { campaignId, status: "CONNECTED" } }),
    prisma.messageTemplate.count({ where: { campaignId } }),
    prisma.dashboard.count({ where: { campaignId } }),
    prisma.broadcast.count({ where: { campaignId } }),
    prisma.broadcast.groupBy({ by: ["status"], where: { campaignId }, _count: { _all: true } }),
    prisma.broadcastMessage.count({ where: { campaignId, status: { in: SENT_STATUSES } } }),
    prisma.broadcastMessage.count({ where: { campaignId, status: "FAILED" } }),
    prisma.user.aggregate({ where: { campaignId }, _max: { lastLoginAt: true } }),
  ]);

  const roles = Object.fromEntries(CAMPAIGN_ROLES.map((r) => [r, { active: 0, inactive: 0 }])) as Record<
    CampaignRole,
    { active: number; inactive: number }
  >;
  for (const row of usersByRole) {
    if (!(row.role in roles)) continue;
    const bucket = roles[row.role as CampaignRole];
    if (row.active) bucket.active += row._count._all;
    else bucket.inactive += row._count._all;
  }

  return {
    roles,
    voters,
    voters7,
    voters30,
    messageable,
    optedOut,
    geolocated,
    connections,
    connectedConnections,
    templates,
    dashboards,
    broadcasts,
    broadcastsByStatus: Object.fromEntries(broadcastsByStatus.map((b) => [b.status, b._count._all])) as Record<string, number>,
    messagesSent,
    messagesFailed,
    lastLoginAt: lastLogin._max.lastLoginAt,
  };
}

export type CampaignUsage = Awaited<ReturnType<typeof getCampaignUsage>>;

export async function listCampaignOptions() {
  return prisma.campaign.findMany({
    select: { id: true, ballotName: true, ballotNumber: true, status: true },
    orderBy: { ballotName: "asc" },
  });
}

/** Trilha de auditoria da plataforma. Não junta dados de eleitores; detalhes são saneados. */
export async function listAuditLogs(filters: AuditFilterParams, pageSize = 50) {
  const and: Prisma.AuditLogWhereInput[] = [];
  if (filters.campaign === PLATFORM_SCOPE) and.push({ campaignId: null });
  else if (filters.campaign) and.push({ campaignId: filters.campaign });
  if (filters.action) and.push({ action: filters.action });
  const range = auditDateRange(filters.from, filters.to);
  if (range) and.push({ createdAt: range });
  const where: Prisma.AuditLogWhereInput = and.length ? { AND: and } : {};

  const [rows, total] = await Promise.all([
    prisma.auditLog.findMany({
      where,
      orderBy: { createdAt: "desc" },
      skip: (filters.page - 1) * pageSize,
      take: pageSize,
      select: {
        id: true,
        createdAt: true,
        action: true,
        entity: true,
        entityId: true,
        ip: true,
        details: true,
        campaign: { select: { id: true, ballotName: true } },
        user: { select: { id: true, name: true, email: true, role: true } },
      },
    }),
    prisma.auditLog.count({ where }),
  ]);

  return {
    total,
    rows: rows.map((r) => ({ ...r, details: sanitizeAuditDetails(r.action, r.entity, r.details) })),
  };
}

/** Dados do próprio super admin para a página de perfil */
export async function getOwnProfile(userId: string) {
  return prisma.user.findUnique({ where: { id: userId }, select: { name: true, email: true, phone: true } });
}
