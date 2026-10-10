// Escopo hierárquico de dados. TODA consulta a eleitores/equipe deve passar por aqui.
//  - ADMIN: toda a campanha
//  - COORDENADOR: ele mesmo + cabos diretamente abaixo dele (parentId = coordenador)
//  - CABO: apenas ele mesmo
// O isolamento entre campanhas é garantido por campaignId em todos os filtros.
import { prisma, type Prisma } from "@/lib/db";
import type { CampaignUser } from "@/lib/auth";
import type { VoterFilters } from "@/lib/voter-filters";
import { normalizeBrPhone } from "@/lib/phone";

/** Mínimo necessário para calcular escopo (permite uso fora do request, ex.: worker) */
export type ScopeUser = Pick<CampaignUser, "id" | "role" | "campaignId">;

/** ids de usuários cuja rede o usuário enxerga; null = campanha inteira (ADMIN) */
export async function getScopeUserIds(user: ScopeUser): Promise<string[] | null> {
  if (user.role === "ADMIN") return null;
  if (user.role === "COORDENADOR") {
    const children = await prisma.user.findMany({
      where: { campaignId: user.campaignId, parentId: user.id },
      select: { id: true },
    });
    return [user.id, ...children.map((c) => c.id)];
  }
  return [user.id];
}

/** where base de eleitores visíveis ao usuário */
export async function voterScopeWhere(user: ScopeUser): Promise<Prisma.VoterWhereInput> {
  const ids = await getScopeUserIds(user);
  return ids ? { campaignId: user.campaignId, registeredById: { in: ids } } : { campaignId: user.campaignId };
}

/** where base de usuários (equipe) visíveis ao usuário */
export function teamScopeWhere(user: ScopeUser): Prisma.UserWhereInput {
  if (user.role === "ADMIN") return { campaignId: user.campaignId };
  if (user.role === "COORDENADOR") {
    return { campaignId: user.campaignId, OR: [{ id: user.id }, { parentId: user.id }] };
  }
  return { campaignId: user.campaignId, id: user.id };
}

/** O usuário pode ver/gerenciar o membro da equipe alvo? (mesma campanha + dentro do escopo) */
export async function canAccessTeamMember(user: ScopeUser, targetUserId: string): Promise<boolean> {
  const found = await prisma.user.findFirst({
    where: { AND: [teamScopeWhere(user), { id: targetUserId }] },
    select: { id: true },
  });
  return !!found;
}

/** Busca um eleitor garantindo escopo (null se não existir ou não for visível) */
export async function findVoterInScope<T extends Prisma.VoterInclude | undefined = undefined>(
  user: ScopeUser,
  voterId: string,
  include?: T,
) {
  const scope = await voterScopeWhere(user);
  return prisma.voter.findFirst({ where: { AND: [scope, { id: voterId }] }, include: include as T });
}

function startOfDay(iso: string): Date {
  return new Date(`${iso}T00:00:00-03:00`);
}
function endOfDay(iso: string): Date {
  return new Date(`${iso}T23:59:59.999-03:00`);
}

/** Converte VoterFilters em where do Prisma, SEM escopo (use buildVoterWhere). */
export async function filtersToWhere(campaignId: string, filters: VoterFilters): Promise<Prisma.VoterWhereInput[]> {
  const and: Prisma.VoterWhereInput[] = [];

  if (filters.q) {
    const q = filters.q.trim();
    const digits = q.replace(/\D/g, "");
    const or: Prisma.VoterWhereInput[] = [{ name: { contains: q } }, { email: { contains: q.toLowerCase() } }];
    if (digits.length >= 4) {
      or.push({ phone: { contains: digits } });
      const normalized = normalizeBrPhone(digits);
      if (normalized) or.push({ phone: normalized });
    }
    and.push({ OR: or });
  }
  if (filters.neighborhoods?.length) and.push({ neighborhood: { in: filters.neighborhoods } });
  if (filters.cities?.length) and.push({ city: { in: filters.cities } });
  if (filters.registeredByIds?.length) and.push({ registeredById: { in: filters.registeredByIds } });
  if (filters.coordinatorIds?.length) {
    const cabos = await prisma.user.findMany({
      where: { campaignId, parentId: { in: filters.coordinatorIds } },
      select: { id: true },
    });
    and.push({ registeredById: { in: [...filters.coordinatorIds, ...cabos.map((c) => c.id)] } });
  }
  if (filters.genders?.length) and.push({ gender: { in: filters.genders } });
  if (filters.supportLevels?.length) and.push({ supportLevel: { in: filters.supportLevels } });
  if (filters.sources?.length) and.push({ source: { in: filters.sources } });
  if (filters.electoralZones?.length) and.push({ electoralZone: { in: filters.electoralZones } });
  if (filters.tags?.length) {
    and.push({ OR: filters.tags.map((t) => ({ tags: { contains: `,${t},` } })) });
  }
  if (filters.ageMin !== undefined || filters.ageMax !== undefined) {
    const now = new Date();
    const birth: Prisma.DateTimeNullableFilter = {};
    if (filters.ageMin !== undefined) {
      // idade >= min  ⇔  nascimento <= hoje - min anos
      birth.lte = new Date(now.getFullYear() - filters.ageMin, now.getMonth(), now.getDate(), 23, 59, 59);
    }
    if (filters.ageMax !== undefined) {
      // idade <= max  ⇔  nascimento > hoje - (max+1) anos
      birth.gt = new Date(now.getFullYear() - filters.ageMax - 1, now.getMonth(), now.getDate(), 23, 59, 59);
    }
    and.push({ birthDate: birth });
  }
  if (filters.createdFrom || filters.createdTo) {
    const created: Prisma.DateTimeFilter = {};
    if (filters.createdFrom) created.gte = startOfDay(filters.createdFrom);
    if (filters.createdTo) created.lte = endOfDay(filters.createdTo);
    and.push({ createdAt: created });
  }
  if (filters.hasGeo === true) and.push({ latitude: { not: null }, longitude: { not: null } });
  if (filters.hasGeo === false) and.push({ OR: [{ latitude: null }, { longitude: null }] });
  if (filters.messageable === true) and.push(MESSAGEABLE_WHERE);
  return and;
}

/** Eleitores aptos a receber disparos: consentiram e não pediram descadastro */
export const MESSAGEABLE_WHERE: Prisma.VoterWhereInput = {
  whatsappOptIn: true,
  optOutAt: null,
  consentAt: { not: null },
};

/** where final = escopo do usuário AND filtros. Filtros nunca ampliam o escopo. */
export async function buildVoterWhere(user: ScopeUser, filters: VoterFilters = {}): Promise<Prisma.VoterWhereInput> {
  const scope = await voterScopeWhere(user);
  const parts = await filtersToWhere(user.campaignId, filters);
  return { AND: [scope, ...parts] };
}
