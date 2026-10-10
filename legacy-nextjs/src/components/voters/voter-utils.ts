// Utilitários puros do módulo de eleitores (sem banco): usados no servidor e no navegador.
import { titleCase } from "@/lib/utils";
import type { GeoStatus } from "@/lib/constants";

const TZ = "America/Sao_Paulo";

/** Código de convite (link/QR) — gerado por randomInviteCode (letras minúsculas e números) */
export const INVITE_CODE_RE = /^[a-z0-9]{4,32}$/i;
export function isValidInviteCode(code: string | null | undefined): code is string {
  return !!code && INVITE_CODE_RE.test(code);
}

export function onlyDigits(value: string | null | undefined): string {
  return (value ?? "").replace(/\D/g, "");
}

// ---------- CEP ----------

/** "13.010-111" → "13010111"; null se não tiver 8 dígitos */
export function normalizeCepInput(value: string | null | undefined): string | null {
  const d = onlyDigits(value);
  return d.length === 8 && d !== "00000000" ? d : null;
}

/** Máscara progressiva "13010111" → "13010-111" */
export function maskCepInput(value: string): string {
  const d = onlyDigits(value).slice(0, 8);
  return d.length > 5 ? `${d.slice(0, 5)}-${d.slice(5)}` : d;
}

export function formatCepDisplay(cep: string | null | undefined): string {
  const d = onlyDigits(cep);
  return d.length === 8 ? `${d.slice(0, 5)}-${d.slice(5)}` : (cep ?? "");
}

// ---------- Datas ----------

export const MIN_VOTER_AGE = 16;
export const MAX_VOTER_AGE = 120;

/** Máscara progressiva "01021990" → "01/02/1990" */
export function maskDateInput(value: string): string {
  const d = onlyDigits(value).slice(0, 8);
  if (d.length <= 2) return d;
  if (d.length <= 4) return `${d.slice(0, 2)}/${d.slice(2)}`;
  return `${d.slice(0, 2)}/${d.slice(2, 4)}/${d.slice(4)}`;
}

/**
 * Data de nascimento informada pelo usuário: "dd/mm/aaaa", "dd-mm-aaaa", "dd.mm.aaaa", "ddmmaaaa" ou "aaaa-mm-dd"
 * (com ou sem horário ISO). Gravada ao meio-dia UTC para não mudar de dia em nenhum fuso do Brasil.
 */
export function parseBirthDateInput(value: string | null | undefined): Date | null {
  const s = (value ?? "").trim();
  if (!s) return null;
  let y: number;
  let m: number;
  let d: number;
  let match: RegExpExecArray | null;
  if ((match = /^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ].*)?$/.exec(s))) {
    [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])];
  } else if ((match = /^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$/.exec(s))) {
    [d, m, y] = [Number(match[1]), Number(match[2]), Number(match[3])];
  } else if ((match = /^(\d{2})(\d{2})(\d{4})$/.exec(s))) {
    [d, m, y] = [Number(match[1]), Number(match[2]), Number(match[3])];
  } else {
    return null;
  }
  if (y < 1800 || m < 1 || m > 12 || d < 1 || d > 31) return null;
  const date = new Date(Date.UTC(y, m - 1, d, 12));
  if (date.getUTCFullYear() !== y || date.getUTCMonth() !== m - 1 || date.getUTCDate() !== d) return null;
  return date;
}

/** Ano/mês/dia de hoje no fuso de São Paulo */
export function saoPauloDateParts(now: Date = new Date()): { year: number; month: number; day: number } {
  const iso = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
  const [year, month, day] = iso.split("-").map(Number);
  return { year, month, day };
}

/** "aaaa-mm-dd" de hoje em São Paulo */
export function saoPauloIsoDate(now: Date = new Date()): string {
  const { year, month, day } = saoPauloDateParts(now);
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/** Início do dia (00:00 de São Paulo, UTC-3 sem horário de verão) de hoje menos `daysAgo` dias */
export function startOfDaySaoPaulo(now: Date = new Date(), daysAgo = 0): Date {
  const base = new Date(`${saoPauloIsoDate(now)}T00:00:00-03:00`);
  return new Date(base.getTime() - daysAgo * 86_400_000);
}

/** Idade em anos completos (componentes UTC da data de nascimento × hoje em São Paulo) */
export function ageFromBirthDate(birth: Date | string | null | undefined, now: Date = new Date()): number | null {
  if (!birth) return null;
  const b = typeof birth === "string" ? new Date(birth) : birth;
  if (Number.isNaN(b.getTime())) return null;
  const today = saoPauloDateParts(now);
  const bm = b.getUTCMonth() + 1;
  const bd = b.getUTCDate();
  let age = today.year - b.getUTCFullYear();
  if (today.month < bm || (today.month === bm && today.day < bd)) age--;
  return age;
}

export function isVoterAge(age: number | null): boolean {
  return age !== null && age >= MIN_VOTER_AGE && age <= MAX_VOTER_AGE;
}

/** Data de nascimento para exibição/edição: "dd/mm/aaaa" */
export function formatBirthDate(value: Date | string | null | undefined): string {
  if (!value) return "";
  const b = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(b.getTime())) return "";
  return `${String(b.getUTCDate()).padStart(2, "0")}/${String(b.getUTCMonth() + 1).padStart(2, "0")}/${b.getUTCFullYear()}`;
}

// ---------- Textos ----------

/** Espaços normalizados; se tudo estiver em minúsculas ou MAIÚSCULAS aplica titleCase (bairro, cidade, rua) */
export function smartCase(value: string): string {
  const v = value.trim().replace(/\s+/g, " ");
  if (!v) return v;
  if (v === v.toLowerCase() || v === v.toUpperCase()) return titleCase(v);
  return v;
}

export function hasLetter(value: string): boolean {
  return /\p{L}/u.test(value);
}

/** Link de compartilhamento no WhatsApp (sem destinatário) */
export function whatsappShareUrl(text: string): string {
  return `https://wa.me/?text=${encodeURIComponent(text)}`;
}

/** "https://efind.com.br/c/abc/" → "efind.com.br/c/abc" */
export function shortUrl(url: string): string {
  return url.replace(/^https?:\/\//i, "").replace(/\/+$/, "");
}

// ---------- Cores da campanha ----------

export const DEFAULT_BRAND_COLOR = "#4f46e5";

export function isHexColor(value: string | null | undefined): value is string {
  return !!value && /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i.test(value.trim());
}

/** Cor validada em "#rrggbb" minúsculo (cai no padrão se inválida) */
export function safeHexColor(value: string | null | undefined, fallback = DEFAULT_BRAND_COLOR): string {
  if (!isHexColor(value)) return fallback;
  let hex = value.trim().toLowerCase().slice(1);
  if (hex.length === 3) hex = hex.split("").map((c) => c + c).join("");
  return `#${hex}`;
}

function hexToRgb(hex: string): [number, number, number] {
  const h = safeHexColor(hex).slice(1);
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

function rgbToHex([r, g, b]: [number, number, number]): string {
  return `#${[r, g, b].map((c) => Math.round(Math.min(255, Math.max(0, c))).toString(16).padStart(2, "0")).join("")}`;
}

/** Mistura `color` com `other` (weight = proporção de `other`, 0–1) */
export function mixHex(color: string, other: string, weight: number): string {
  const a = hexToRgb(color);
  const b = hexToRgb(other);
  return rgbToHex([a[0] + (b[0] - a[0]) * weight, a[1] + (b[1] - a[1]) * weight, a[2] + (b[2] - a[2]) * weight]);
}

function luminance(hex: string): number {
  const [r, g, b] = hexToRgb(hex).map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [l1, l2] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (l1 + 0.05) / (l2 + 0.05);
}

/** Cor de texto legível sobre o fundo: branco ou grafite */
export function readableTextColor(background: string): "#ffffff" | "#0f172a" {
  const bg = safeHexColor(background);
  return contrast(bg, "#ffffff") >= contrast(bg, "#0f172a") ? "#ffffff" : "#0f172a";
}

/**
 * Variáveis CSS que recolorem as classes brand-* do Tailwind v4 com a cor da campanha
 * (aplicar via style no contêiner das páginas públicas).
 */
export function brandCssVars(color: string): Record<string, string> {
  const c = safeHexColor(color);
  return {
    "--color-brand-50": mixHex(c, "#ffffff", 0.92),
    "--color-brand-100": mixHex(c, "#ffffff", 0.84),
    "--color-brand-200": mixHex(c, "#ffffff", 0.68),
    "--color-brand-300": mixHex(c, "#ffffff", 0.48),
    "--color-brand-400": mixHex(c, "#ffffff", 0.24),
    "--color-brand-500": mixHex(c, "#ffffff", 0.08),
    "--color-brand-600": c,
    "--color-brand-700": mixHex(c, "#000000", 0.15),
    "--color-brand-800": mixHex(c, "#000000", 0.3),
  };
}

// ---------- Situação do eleitor ----------

export type WhatsappStatus = "APTO" | "DESCADASTRADO" | "SEM_AUTORIZACAO";
export const WHATSAPP_STATUS_LABELS: Record<WhatsappStatus, string> = {
  APTO: "Apto a WhatsApp",
  DESCADASTRADO: "Descadastrado",
  SEM_AUTORIZACAO: "Sem autorização",
};

/** Mesma regra de MESSAGEABLE_WHERE: opt-in, consentimento e sem descadastro */
export function whatsappStatusOf(v: {
  whatsappOptIn: boolean;
  optOutAt: Date | string | null;
  consentAt: Date | string | null;
}): WhatsappStatus {
  if (v.optOutAt) return "DESCADASTRADO";
  if (v.whatsappOptIn && v.consentAt) return "APTO";
  return "SEM_AUTORIZACAO";
}

export const GEO_STATUS_LABELS: Record<GeoStatus, string> = {
  PENDING: "Aguardando localização",
  OK: "Localizado pelo CEP/rua",
  APPROXIMATE: "Localização aproximada (bairro/cidade)",
  FAILED: "Não foi possível localizar",
};

// ---------- Ordenação da lista ----------

export const VOTER_SORTS = {
  recentes: "Mais recentes",
  antigos: "Mais antigos",
  nome: "Nome (A–Z)",
} as const;
export type VoterSort = keyof typeof VOTER_SORTS;

export function parseVoterSort(value: string | string[] | undefined): VoterSort {
  const v = Array.isArray(value) ? value[0] : value;
  return v && v in VOTER_SORTS ? (v as VoterSort) : "recentes";
}
