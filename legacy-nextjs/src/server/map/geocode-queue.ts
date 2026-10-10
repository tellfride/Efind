// "Localizar pendentes agora" (ADMIN): reprocessa a fila de geocodificação SOMENTE da campanha do usuário.
// Usa geocodeVoter (src/server/geo/geocode.ts) eleitor a eleitor — processPendingGeocoding não filtra por
// campanha e gastaria o tempo da ação com eleitores de outras campanhas.
import { prisma } from "@/lib/db";
import { geocodeVoter } from "@/server/geo/geocode";
import { summarizeGeocodeRun } from "./geocode-summary";
import type { GeocodeRunResult } from "./types";

/** Tempo máximo da ação: o Nominatim aceita 1 requisição/s, então não iniciamos novos eleitores após isso */
const TIME_BUDGET_MS = 25_000;

export async function runCampaignGeocoding(campaignId: string, limit = 15): Promise<GeocodeRunResult> {
  // Primeiro os que nunca foram processados; depois os que falharam (os mais antigos antes)
  const pending = await prisma.voter.findMany({
    where: { campaignId, geoStatus: "PENDING" },
    orderBy: { createdAt: "asc" },
    take: limit,
    select: { id: true },
  });
  const failed =
    pending.length < limit
      ? await prisma.voter.findMany({
          where: { campaignId, geoStatus: "FAILED" },
          orderBy: { updatedAt: "asc" },
          take: limit - pending.length,
          select: { id: true },
        })
      : [];

  // Falhas voltam para a fila (o worker continua o restante em segundo plano)
  await prisma.voter.updateMany({ where: { campaignId, geoStatus: "FAILED" }, data: { geoStatus: "PENDING" } });

  const ids = [...pending, ...failed].map((v) => v.id);
  const startedAt = Date.now();
  const processed: string[] = [];
  for (const id of ids) {
    if (Date.now() - startedAt > TIME_BUDGET_MS) break;
    try {
      await geocodeVoter(id);
    } catch (err) {
      console.error("[mapa] falha ao geocodificar eleitor:", err instanceof Error ? err.message : "erro desconhecido");
      await prisma.voter.updateMany({ where: { id, campaignId }, data: { geoStatus: "FAILED" } }).catch(() => null);
    }
    processed.push(id);
  }

  const [statuses, remaining] = await Promise.all([
    processed.length
      ? prisma.voter.findMany({ where: { campaignId, id: { in: processed } }, select: { geoStatus: true } })
      : Promise.resolve([] as { geoStatus: string }[]),
    prisma.voter.count({ where: { campaignId, geoStatus: "PENDING" } }),
  ]);

  return summarizeGeocodeRun(
    statuses.map((s) => s.geoStatus),
    remaining,
  );
}
