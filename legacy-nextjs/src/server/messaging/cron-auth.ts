// Autenticação do endpoint /api/cron/tick: "Authorization: Bearer <CRON_SECRET>" ou ?secret=<CRON_SECRET>.
import { createHash, timingSafeEqual } from "node:crypto";

/** Comparação em tempo constante (hash antes para igualar tamanhos) */
export function safeCompare(a: string, b: string): boolean {
  const ha = createHash("sha256").update(a, "utf8").digest();
  const hb = createHash("sha256").update(b, "utf8").digest();
  return timingSafeEqual(ha, hb) && a.length === b.length;
}

export type CronAuthResult = "ok" | "not_configured" | "unauthorized";

export function checkCronAuth(input: { secret: string; authorization: string | null; querySecret: string | null }): CronAuthResult {
  if (!input.secret) return "not_configured";
  const bearer = /^Bearer\s+(.+)$/i.exec(input.authorization?.trim() ?? "")?.[1]?.trim() ?? "";
  const query = input.querySecret?.trim() ?? "";
  // Avalia as duas formas sempre, para não vazar qual delas foi usada pelo tempo de resposta
  const byHeader = bearer ? safeCompare(bearer, input.secret) : false;
  const byQuery = query ? safeCompare(query, input.secret) : false;
  return byHeader || byQuery ? "ok" : "unauthorized";
}
