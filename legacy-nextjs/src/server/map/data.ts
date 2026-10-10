// Leitura dos dados do mapa, sempre dentro da campanha e do escopo hierárquico do usuário.
import { prisma } from "@/lib/db";
import type { CampaignUser } from "@/lib/auth";
import { can } from "@/lib/permissions";
import type { VoterFilters } from "@/lib/voter-filters";
import { buildVoterWhere, teamScopeWhere } from "@/server/access";
import { aggregateMapData, MAP_POINT_LIMIT } from "./aggregate";
import type { GeoQueueCounts, MapData } from "./types";

/** Dados agregados do mapa para os filtros informados (o filtro "hasGeo" não se aplica ao mapa) */
export async function loadMapData(user: CampaignUser, filters: VoterFilters): Promise<MapData> {
  const { hasGeo: _ignored, ...mapFilters } = filters;
  const where = await buildVoterWhere(user, mapFilters);

  const [rows, members] = await Promise.all([
    prisma.voter.findMany({
      where,
      select: {
        id: true,
        latitude: true,
        longitude: true,
        geoStatus: true,
        neighborhood: true,
        city: true,
        supportLevel: true,
        whatsappOptIn: true,
        optOutAt: true,
        consentAt: true,
        registeredById: true,
      },
      orderBy: { createdAt: "asc" },
    }),
    // Quem cadastrou sempre está no escopo de equipe do usuário (mesma regra de voterScopeWhere)
    prisma.user.findMany({ where: teamScopeWhere(user), select: { id: true, name: true } }),
  ]);

  return aggregateMapData(rows, {
    memberNames: new Map(members.map((m) => [m.id, m.name])),
    canViewVoters: can(user.permissions, "eleitores", "view"),
    pointLimit: MAP_POINT_LIMIT,
  });
}

/** Eleitores da campanha aguardando (PENDING) ou que falharam (FAILED) na geocodificação */
export async function getGeoQueueCounts(campaignId: string): Promise<GeoQueueCounts> {
  const groups = await prisma.voter.groupBy({
    by: ["geoStatus"],
    where: { campaignId, geoStatus: { in: ["PENDING", "FAILED"] } },
    _count: { _all: true },
  });
  const get = (status: string) => groups.find((g) => g.geoStatus === status)?._count._all ?? 0;
  return { pending: get("PENDING"), failed: get("FAILED") };
}
