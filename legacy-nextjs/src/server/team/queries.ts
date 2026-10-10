// Leituras do módulo Equipe (Server Components e Server Actions). Toda consulta passa pelo
// escopo hierárquico de src/server/access.ts e pelo campaignId do usuário logado.
import { prisma, type Prisma } from "@/lib/db";
import type { CampaignUser } from "@/lib/auth";
import { teamScopeWhere, voterScopeWhere, type ScopeUser } from "@/server/access";
import { randomInviteCode } from "@/lib/crypto";
import { formatPhone } from "@/lib/phone";
import { formatDateTime } from "@/lib/utils";
import { isCampaignRole, startOfDayInSaoPaulo, type ParentCandidate } from "./rules";
import type { CampaignRole } from "@/lib/constants";
import type { MemberOption, TeamMemberDTO } from "@/components/team/types";

const DAY_MS = 86_400_000;

function asRole(role: string): CampaignRole {
  return isCampaignRole(role) ? role : "CABO";
}

/** Membros visíveis ao usuário com total de eleitores e cadastros dos últimos 7 dias (2 groupBy, sem N+1) */
export async function loadTeamMembers(user: CampaignUser): Promise<TeamMemberDTO[]> {
  const since7d = new Date(Date.now() - 7 * DAY_MS);
  const [members, voterScope] = await Promise.all([
    prisma.user.findMany({
      where: teamScopeWhere(user),
      select: {
        id: true,
        name: true,
        email: true,
        phone: true,
        role: true,
        parentId: true,
        active: true,
        goal: true,
        region: true,
        lastLoginAt: true,
        parent: { select: { name: true, role: true } },
      },
      orderBy: { name: "asc" },
    }),
    voterScopeWhere(user),
  ]);

  const [totals, recent] = await Promise.all([
    prisma.voter.groupBy({ by: ["registeredById"], where: voterScope, _count: { _all: true } }),
    prisma.voter.groupBy({
      by: ["registeredById"],
      where: { AND: [voterScope, { createdAt: { gte: since7d } }] },
      _count: { _all: true },
    }),
  ]);
  const totalBy = new Map(totals.map((t) => [t.registeredById, t._count._all]));
  const recentBy = new Map(recent.map((t) => [t.registeredById, t._count._all]));

  return members
    .filter((m) => isCampaignRole(m.role))
    .map((m) => ({
      id: m.id,
      name: m.name,
      email: m.email,
      phone: m.phone ? formatPhone(m.phone) : null,
      role: asRole(m.role),
      parentId: m.parentId,
      parentName: m.parent?.name ?? null,
      parentRole: m.parent && isCampaignRole(m.parent.role) ? m.parent.role : null,
      active: m.active,
      goal: m.goal,
      region: m.region,
      votersTotal: totalBy.get(m.id) ?? 0,
      voters7d: recentBy.get(m.id) ?? 0,
      lastLoginLabel: m.lastLoginAt ? formatDateTime(m.lastLoginAt) : "Nunca acessou",
      isSelf: m.id === user.id,
    }));
}

/** Detalhe de um membro (null se não existir ou estiver fora do escopo do usuário) */
export async function loadMemberDetail(user: CampaignUser, memberId: string, opts: { includeRecentVoters: boolean }) {
  const member = await prisma.user.findFirst({
    where: { AND: [teamScopeWhere(user), { id: memberId }] },
    select: {
      id: true,
      name: true,
      email: true,
      phone: true,
      role: true,
      parentId: true,
      active: true,
      goal: true,
      region: true,
      inviteCode: true,
      lastLoginAt: true,
      createdAt: true,
      parent: { select: { id: true, name: true, role: true, active: true } },
    },
  });
  if (!member || !isCampaignRole(member.role)) return null;

  const voterScope = await voterScopeWhere(user);
  const own: Prisma.VoterWhereInput = { AND: [voterScope, { registeredById: member.id }] };
  const since = (date: Date): Prisma.VoterWhereInput => ({ AND: [voterScope, { registeredById: member.id }, { createdAt: { gte: date } }] });
  const now = Date.now();

  const [total, today, last7d, last30d, neighborhoods, recentVoters, children] = await Promise.all([
    prisma.voter.count({ where: own }),
    prisma.voter.count({ where: since(startOfDayInSaoPaulo()) }),
    prisma.voter.count({ where: since(new Date(now - 7 * DAY_MS)) }),
    prisma.voter.count({ where: since(new Date(now - 30 * DAY_MS)) }),
    prisma.voter.groupBy({
      by: ["neighborhood"],
      where: { AND: [voterScope, { registeredById: member.id }, { neighborhood: { not: null } }, { NOT: { neighborhood: "" } }] },
      _count: { _all: true },
      orderBy: { _count: { neighborhood: "desc" } },
      take: 5,
    }),
    opts.includeRecentVoters
      ? prisma.voter.findMany({
          where: own,
          select: { id: true, name: true, neighborhood: true, createdAt: true },
          orderBy: { createdAt: "desc" },
          take: 10,
        })
      : Promise.resolve([]),
    prisma.user.findMany({
      where: { AND: [teamScopeWhere(user), { parentId: member.id }] },
      select: { id: true, name: true, role: true, active: true, goal: true },
      orderBy: { name: "asc" },
    }),
  ]);

  let childCounts = new Map<string, number>();
  if (children.length) {
    const grouped = await prisma.voter.groupBy({
      by: ["registeredById"],
      where: { AND: [voterScope, { registeredById: { in: children.map((c) => c.id) } }] },
      _count: { _all: true },
    });
    childCounts = new Map(grouped.map((g) => [g.registeredById, g._count._all]));
  }

  return {
    member: { ...member, role: member.role as CampaignRole },
    stats: { total, today, last7d, last30d },
    neighborhoods: neighborhoods.map((n) => ({ name: n.neighborhood ?? "", count: n._count._all })),
    recentVoters,
    children: children
      .filter((c) => isCampaignRole(c.role))
      .map((c) => ({ ...c, role: c.role as CampaignRole, votersTotal: childCounts.get(c.id) ?? 0 })),
  };
}

/** Administradores e coordenadores ativos da campanha (opções de superior) */
export async function loadPlacementOptions(campaignId: string): Promise<{ admins: MemberOption[]; coordinators: MemberOption[] }> {
  const rows = await prisma.user.findMany({
    where: { campaignId, active: true, role: { in: ["ADMIN", "COORDENADOR"] } },
    select: { id: true, name: true, role: true, active: true },
    orderBy: { name: "asc" },
  });
  const options = rows.map((r) => ({ ...r, role: asRole(r.role) }));
  return {
    admins: options.filter((o) => o.role === "ADMIN"),
    coordinators: options.filter((o) => o.role === "COORDENADOR"),
  };
}

/** Membros ativos do escopo do usuário (ex.: quem pode receber eleitores transferidos) */
export async function loadActiveScopeMembers(user: ScopeUser): Promise<MemberOption[]> {
  const rows = await prisma.user.findMany({
    where: { AND: [teamScopeWhere(user), { active: true }] },
    select: { id: true, name: true, role: true, active: true },
    orderBy: { name: "asc" },
  });
  return rows.filter((r) => isCampaignRole(r.role)).map((r) => ({ ...r, role: r.role as CampaignRole }));
}

/** Busca um membro garantindo campanha + escopo hierárquico do usuário */
export async function findMemberInScope(user: ScopeUser, memberId: string) {
  return prisma.user.findFirst({
    where: { AND: [teamScopeWhere(user), { id: memberId }] },
    select: {
      id: true,
      name: true,
      email: true,
      phone: true,
      role: true,
      parentId: true,
      active: true,
      goal: true,
      region: true,
      inviteCode: true,
    },
  });
}

/** Usuários da campanha com os ids informados (para validar superiores) */
export async function loadCandidates(campaignId: string, ids: (string | null | undefined)[]): Promise<ParentCandidate[]> {
  const unique = Array.from(new Set(ids.filter((v): v is string => !!v)));
  if (!unique.length) return [];
  return prisma.user.findMany({
    where: { campaignId, id: { in: unique } },
    select: { id: true, role: true, active: true },
  });
}

export async function countOtherActiveAdmins(campaignId: string, excludeId: string): Promise<number> {
  return prisma.user.count({ where: { campaignId, role: "ADMIN", active: true, id: { not: excludeId } } });
}

export async function hasActiveCoordinators(campaignId: string, excludeId?: string): Promise<boolean> {
  const n = await prisma.user.count({
    where: { campaignId, role: "COORDENADOR", active: true, ...(excludeId ? { id: { not: excludeId } } : {}) },
  });
  return n > 0;
}

/** Código de convite garantidamente único (link/QR de cadastro) */
export async function uniqueInviteCode(): Promise<string> {
  for (let attempt = 0; attempt < 10; attempt++) {
    const code = randomInviteCode(attempt < 5 ? 8 : 10);
    const exists = await prisma.user.findUnique({ where: { inviteCode: code }, select: { id: true } });
    if (!exists) return code;
  }
  throw new Error("Não foi possível gerar um código de convite único.");
}

/** Violação de unicidade do Prisma (P2002), opcionalmente num campo específico */
export function isUniqueViolation(err: unknown, field?: string): boolean {
  if (!err || typeof err !== "object" || (err as { code?: string }).code !== "P2002") return false;
  if (!field) return true;
  const target = (err as { meta?: { target?: unknown } }).meta?.target;
  return Array.isArray(target) ? target.includes(field) : typeof target === "string" ? target.includes(field) : true;
}
