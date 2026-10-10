// Agendamento de disparos: o horário digitado (datetime-local) é sempre interpretado no fuso da
// campanha (America/Sao_Paulo), independentemente do fuso do navegador ou do servidor. Puro.

export const CAMPAIGN_TZ = "America/Sao_Paulo";
/** Antecedência máxima de um agendamento */
export const MAX_SCHEDULE_DAYS = 180;

const LOCAL_RE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/;

/** Diferença (ms) entre o relógio local do fuso e UTC no instante informado */
function tzOffsetMs(instant: number, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(new Date(instant));
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? 0);
  const asUtc = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour") % 24, get("minute"), get("second"));
  return asUtc - Math.floor(instant / 1000) * 1000;
}

/** "2026-10-20T14:30" (horário de Brasília) → Date em UTC. null se inválido. */
export function zonedLocalToUtc(local: string, timeZone: string = CAMPAIGN_TZ): Date | null {
  const m = LOCAL_RE.exec(local.trim());
  if (!m) return null;
  const [y, mo, d, h, mi, s] = [m[1], m[2], m[3], m[4], m[5], m[6] ?? "0"].map(Number);
  if (mo < 1 || mo > 12 || d < 1 || d > 31 || h > 23 || mi > 59 || s > 59) return null;
  const naive = Date.UTC(y, mo - 1, d, h, mi, s);
  const check = new Date(naive);
  if (check.getUTCMonth() !== mo - 1 || check.getUTCDate() !== d) return null; // ex.: 31/02
  // Duas passadas para acertar o deslocamento perto de mudanças de horário
  let utc = naive - tzOffsetMs(naive, timeZone);
  utc = naive - tzOffsetMs(utc, timeZone);
  return new Date(utc);
}

/** Date → "YYYY-MM-DDTHH:mm" no fuso da campanha (valor para <input type="datetime-local">) */
export function toZonedLocalInput(date: Date, timeZone: string = CAMPAIGN_TZ): string {
  const shifted = new Date(date.getTime() + tzOffsetMs(date.getTime(), timeZone));
  return shifted.toISOString().slice(0, 16);
}

export type ScheduleValidation = { ok: true; date: Date } | { ok: false; error: string };

/** Valida o horário de agendamento: precisa ser no futuro e dentro do limite de antecedência */
export function validateSchedule(local: string | null | undefined, now: Date = new Date()): ScheduleValidation {
  if (!local) return { ok: false, error: "Informe a data e a hora do envio." };
  const date = zonedLocalToUtc(local);
  if (!date) return { ok: false, error: "Data ou hora inválida." };
  if (date.getTime() <= now.getTime()) return { ok: false, error: "Escolha um horário no futuro." };
  if (date.getTime() > now.getTime() + MAX_SCHEDULE_DAYS * 86_400_000) {
    return { ok: false, error: `O agendamento pode ser feito para no máximo ${MAX_SCHEDULE_DAYS} dias à frente.` };
  }
  return { ok: true, date };
}

/** Duração estimada (minutos) para enviar `count` mensagens a `ratePerMinute` */
export function estimateDurationMinutes(count: number, ratePerMinute: number): number {
  if (count <= 0) return 0;
  return Math.ceil(count / Math.max(1, ratePerMinute));
}

/** 0 → "—"; 1 → "cerca de 1 min"; 135 → "cerca de 2 h 15 min"; 1500 → "cerca de 1 dia e 1 h" */
export function formatDuration(minutes: number): string {
  if (!Number.isFinite(minutes) || minutes <= 0) return "—";
  const m = Math.ceil(minutes);
  if (m < 60) return `cerca de ${m} min`;
  const days = Math.floor(m / 1440);
  const hours = Math.floor((m % 1440) / 60);
  const mins = m % 60;
  if (days > 0) {
    return `cerca de ${days} ${days === 1 ? "dia" : "dias"}${hours ? ` e ${hours} h` : ""}`;
  }
  return `cerca de ${hours} h${mins ? ` ${String(mins).padStart(2, "0")} min` : ""}`;
}
