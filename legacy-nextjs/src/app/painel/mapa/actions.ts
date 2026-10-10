"use server";

import { revalidatePath } from "next/cache";
import { authorize } from "@/lib/auth";
import { audit } from "@/lib/audit";
import { actionError, actionOk, type ActionResult } from "@/lib/action-result";
import { rateLimit } from "@/lib/rate-limit";
import { runCampaignGeocoding } from "@/server/map/geocode-queue";
import { geocodeRunMessage } from "@/server/map/geocode-summary";
import type { GeocodeRunResult } from "@/server/map/types";

/** "Localizar pendentes agora" — apenas ADMIN; reprocessa a fila de geocodificação da própria campanha */
export async function geocodePendingAction(
  _prev: ActionResult<GeocodeRunResult>,
  _formData: FormData,
): Promise<ActionResult<GeocodeRunResult>> {
  const auth = await authorize("mapa", "view");
  if (!auth.ok) return actionError(auth.error);
  const { user } = auth;
  if (user.role !== "ADMIN") return actionError("Apenas administradores podem fazer isso.");

  const limit = rateLimit(`mapa-geocode:${user.campaignId}`, 6, 10 * 60_000);
  if (!limit.ok) {
    return actionError(`Muitas execuções seguidas. Tente novamente em ${Math.ceil(limit.retryAfterSeconds / 60)} min.`);
  }

  let result: GeocodeRunResult;
  try {
    result = await runCampaignGeocoding(user.campaignId, 15);
  } catch (err) {
    console.error("[mapa] falha na geocodificação:", err instanceof Error ? err.message : "erro desconhecido");
    return actionError("Não foi possível localizar os eleitores agora. Tente novamente em instantes.");
  }

  await audit({
    action: "voter.geocode_retry",
    campaignId: user.campaignId,
    userId: user.id,
    entity: "Voter",
    details: { ...result },
  });
  revalidatePath("/painel/mapa");
  return actionOk(geocodeRunMessage(result), result);
}
