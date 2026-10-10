// Opções para o painel de filtros de eleitores (bairros, cidades, equipe, tags...), sempre dentro do escopo do usuário.
import { prisma } from "@/lib/db";
import type { CampaignUser } from "@/lib/auth";
import { parseTags } from "@/lib/utils";
import { teamScopeWhere, voterScopeWhere } from "./access";

export interface FilterOption {
  value: string;
  label: string;
  count?: number;
  /** Texto auxiliar (ex.: papel do membro, cidade do bairro) */
  hint?: string;
}

export interface VoterFilterOptions {
  neighborhoods: FilterOption[];
  cities: FilterOption[];
  coordinators: FilterOption[];
  members: FilterOption[];
  tags: FilterOption[];
  electoralZones: FilterOption[];
}

const ROLE_HINT: Record<string, string> = { ADMIN: "Administrador", COORDENADOR: "Coordenador", CABO: "Cabo eleitoral" };

export async function getVoterFilterOptions(user: CampaignUser): Promise<VoterFilterOptions> {
  const scope = await voterScopeWhere(user);

  const [byNeighborhood, byCity, byZone, tagRows, team] = await Promise.all([
    prisma.voter.groupBy({
      by: ["neighborhood", "city"],
      where: { AND: [scope, { neighborhood: { not: null } }] },
      _count: { _all: true },
    }),
    prisma.voter.groupBy({ by: ["city"], where: { AND: [scope, { city: { not: null } }] }, _count: { _all: true } }),
    prisma.voter.groupBy({
      by: ["electoralZone"],
      where: { AND: [scope, { electoralZone: { not: null } }] },
      _count: { _all: true },
    }),
    prisma.voter.findMany({ where: { AND: [scope, { tags: { not: null } }] }, select: { tags: true }, take: 20000 }),
    prisma.user.findMany({
      where: teamScopeWhere(user),
      select: { id: true, name: true, role: true, active: true },
      orderBy: { name: "asc" },
    }),
  ]);

  // Bairros com o mesmo nome em cidades diferentes são somados (o filtro é por nome do bairro)
  const nb = new Map<string, { count: number; cities: Set<string> }>();
  for (const r of byNeighborhood) {
    if (!r.neighborhood) continue;
    const entry = nb.get(r.neighborhood) ?? { count: 0, cities: new Set<string>() };
    entry.count += r._count._all;
    if (r.city) entry.cities.add(r.city);
    nb.set(r.neighborhood, entry);
  }
  const neighborhoods = [...nb.entries()]
    .map(([value, e]) => ({ value, label: value, count: e.count, hint: [...e.cities].join(", ") }))
    .sort((a, b) => a.label.localeCompare(b.label, "pt-BR"));

  const tagCount = new Map<string, number>();
  for (const r of tagRows) for (const t of parseTags(r.tags)) tagCount.set(t, (tagCount.get(t) ?? 0) + 1);

  return {
    neighborhoods,
    cities: byCity
      .filter((r) => r.city)
      .map((r) => ({ value: r.city!, label: r.city!, count: r._count._all }))
      .sort((a, b) => a.label.localeCompare(b.label, "pt-BR")),
    coordinators:
      user.role === "ADMIN"
        ? team.filter((m) => m.role === "COORDENADOR").map((m) => ({ value: m.id, label: m.name, hint: m.active ? undefined : "inativo" }))
        : [],
    members: team.map((m) => ({ value: m.id, label: m.name, hint: `${ROLE_HINT[m.role] ?? m.role}${m.active ? "" : " · inativo"}` })),
    tags: [...tagCount.entries()]
      .map(([value, count]) => ({ value, label: value, count }))
      .sort((a, b) => (b.count ?? 0) - (a.count ?? 0)),
    electoralZones: byZone
      .filter((r) => r.electoralZone)
      .map((r) => ({ value: r.electoralZone!, label: `Zona ${r.electoralZone}`, count: r._count._all })),
  };
}
