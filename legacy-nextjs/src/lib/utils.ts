import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const TZ = "America/Sao_Paulo";

export function formatDate(value: Date | string | null | undefined): string {
  if (!value) return "—";
  const d = typeof value === "string" ? new Date(value) : value;
  return d.toLocaleDateString("pt-BR", { timeZone: TZ });
}

export function formatDateTime(value: Date | string | null | undefined): string {
  if (!value) return "—";
  const d = typeof value === "string" ? new Date(value) : value;
  return d.toLocaleString("pt-BR", { timeZone: TZ, dateStyle: "short", timeStyle: "short" });
}

export function formatNumber(value: number | null | undefined): string {
  return (value ?? 0).toLocaleString("pt-BR");
}

export function formatPercent(value: number, digits = 1): string {
  return `${(Number.isFinite(value) ? value : 0).toLocaleString("pt-BR", { maximumFractionDigits: digits })}%`;
}

/** Remove acentos e baixa caixa — útil para comparar bairros/tags */
export function normalizeText(value: string): string {
  return value.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
}

export function slugify(value: string): string {
  return normalizeText(value)
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
}

/** Nome próprio: "MARIA DA SILVA" → "Maria da Silva" */
export function titleCase(value: string): string {
  const lower = new Set(["da", "de", "do", "das", "dos", "e"]);
  return value
    .trim()
    .replace(/\s+/g, " ")
    .toLowerCase()
    .split(" ")
    .map((w, i) => (i > 0 && lower.has(w) ? w : w.charAt(0).toUpperCase() + w.slice(1)))
    .join(" ");
}

export function firstName(fullName: string | null | undefined): string {
  return (fullName ?? "").trim().split(/\s+/)[0] ?? "";
}

export function initials(name: string | null | undefined): string {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return ((parts[0][0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

/** Tags: entrada livre "Saúde, Jovem" → string armazenada ",saude,jovem," */
export function serializeTags(input: string | string[] | null | undefined): string | null {
  const list = (Array.isArray(input) ? input : (input ?? "").split(","))
    .map((t) => slugify(t))
    .filter(Boolean);
  const unique = Array.from(new Set(list));
  return unique.length ? `,${unique.join(",")},` : null;
}

export function parseTags(stored: string | null | undefined): string[] {
  return (stored ?? "").split(",").filter(Boolean);
}

/** Idade em anos completos */
export function ageFrom(birthDate: Date | string | null | undefined, now = new Date()): number | null {
  if (!birthDate) return null;
  const b = typeof birthDate === "string" ? new Date(birthDate) : birthDate;
  let age = now.getFullYear() - b.getFullYear();
  const m = now.getMonth() - b.getMonth();
  if (m < 0 || (m === 0 && now.getDate() < b.getDate())) age--;
  return age;
}

/** IP do cliente a partir dos headers do proxy */
export function getClientIp(headers: Headers): string {
  const fwd = headers.get("x-forwarded-for");
  if (fwd) return fwd.split(",")[0].trim();
  return headers.get("x-real-ip") ?? "0.0.0.0";
}

/** Converte linhas em CSV (separador ";" para abrir corretamente no Excel pt-BR) com BOM UTF-8 */
export function toCsv(rows: Record<string, unknown>[], columns: { key: string; label: string }[]): string {
  const esc = (v: unknown) => {
    if (v === null || v === undefined) return "";
    let s = v instanceof Date ? v.toISOString() : String(v);
    // Evita injeção de fórmulas no Excel
    if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
    return /[";\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const header = columns.map((c) => esc(c.label)).join(";");
  const body = rows.map((r) => columns.map((c) => esc(r[c.key])).join(";")).join("\r\n");
  return `﻿${header}\r\n${body}`;
}
