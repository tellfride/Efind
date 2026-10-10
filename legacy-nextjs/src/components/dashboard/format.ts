// Formatação usada pelos widgets (pt-BR). Puro — seguro no cliente.
import { formatDistanceToNowStrict } from "date-fns";
import { ptBR } from "date-fns/locale";

/** "2026-10-09" → "09/10" */
export function formatDayShort(key: string): string {
  const [, m, d] = key.split("-");
  return d && m ? `${d}/${m}` : key;
}

/** "2026-10-09" → "sex., 09/10/2026" */
export function formatDayLong(key: string): string {
  const date = new Date(`${key}T12:00:00Z`);
  if (Number.isNaN(date.getTime())) return key;
  return date.toLocaleDateString("pt-BR", { timeZone: "UTC", weekday: "short", day: "2-digit", month: "2-digit", year: "numeric" });
}

/** "há 5 minutos", "há 2 dias"; menos de 1 minuto → "agora mesmo" */
export function relativeTime(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  if (Math.abs(now.getTime() - date.getTime()) < 60_000) return "agora mesmo";
  return formatDistanceToNowStrict(date, { locale: ptBR, addSuffix: true });
}

/** Variação percentual com sinal: +12,5% / −3% */
export function formatDelta(value: number): string {
  const abs = Math.abs(value).toLocaleString("pt-BR", { maximumFractionDigits: 1 });
  if (value > 0) return `+${abs}%`;
  if (value < 0) return `−${abs}%`;
  return "0%";
}

/** Número compacto para eixos: 1.200 → "1,2 mil" */
export function formatCompact(value: number): string {
  if (Math.abs(value) < 10_000) return value.toLocaleString("pt-BR");
  return value.toLocaleString("pt-BR", { notation: "compact", maximumFractionDigits: 1 });
}

/** Plural simples: plural(1, "cadastro", "cadastros") */
export function plural(n: number, one: string, many: string): string {
  return `${n.toLocaleString("pt-BR")} ${n === 1 ? one : many}`;
}
