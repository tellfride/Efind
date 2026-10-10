// Resumo de uma rodada de geocodificação (puro — testado em tests/map-geocode.test.ts).
import { formatNumber } from "@/lib/utils";
import type { GeocodeRunResult } from "./types";

export function summarizeGeocodeRun(statuses: readonly string[], remaining: number): GeocodeRunResult {
  let located = 0;
  let failed = 0;
  for (const s of statuses) {
    if (s === "OK" || s === "APPROXIMATE") located++;
    else if (s === "FAILED") failed++;
  }
  return { processed: statuses.length, located, failed, remaining: Math.max(0, remaining) };
}

const plural = (n: number, one: string, many: string) => `${formatNumber(n)} ${n === 1 ? one : many}`;

/** Mensagem exibida no toast após "Localizar pendentes agora" */
export function geocodeRunMessage(r: GeocodeRunResult): string {
  if (r.processed === 0) return "Não há eleitores pendentes de localização.";
  const parts = [plural(r.located, "eleitor localizado", "eleitores localizados")];
  if (r.failed) parts.push(plural(r.failed, "endereço não encontrado", "endereços não encontrados"));
  const tail = r.remaining
    ? ` ${plural(r.remaining, "eleitor continua", "eleitores continuam")} na fila e ${r.remaining === 1 ? "será processado" : "serão processados"} em segundo plano.`
    : "";
  return `${parts.join(", ")}.${tail}`;
}
