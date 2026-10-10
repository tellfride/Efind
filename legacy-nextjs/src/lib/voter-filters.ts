// Filtros de eleitores compartilhados por: lista de eleitores, mapa, dashboards e público dos disparos.
// Puro (sem banco) — pode ser usado em componentes cliente. O "where" do Prisma é montado em
// src/server/access.ts → buildVoterWhere(user, filters), que SEMPRE aplica o escopo do usuário.
import { z } from "zod";
import { GENDERS, SUPPORT_LEVELS, VOTER_SOURCES } from "./constants";

const strList = z.array(z.string().trim().min(1).max(120)).max(200);

export const voterFiltersSchema = z.object({
  /** Busca livre: nome, telefone ou e-mail */
  q: z.string().trim().max(100).optional(),
  neighborhoods: strList.optional(),
  cities: strList.optional(),
  /** Quem cadastrou (ids de usuários) */
  registeredByIds: strList.optional(),
  /** Coordenadores: inclui o próprio coordenador e todos os cabos abaixo dele */
  coordinatorIds: strList.optional(),
  genders: z.array(z.enum(GENDERS)).optional(),
  supportLevels: z.array(z.enum(SUPPORT_LEVELS)).optional(),
  sources: z.array(z.enum(VOTER_SOURCES)).optional(),
  tags: strList.optional(),
  electoralZones: strList.optional(),
  ageMin: z.number().int().min(0).max(130).optional(),
  ageMax: z.number().int().min(0).max(130).optional(),
  /** ISO yyyy-mm-dd (inclusive) */
  createdFrom: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(),
  createdTo: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(),
  /** true = apenas com coordenadas; false = apenas sem */
  hasGeo: z.boolean().optional(),
  /** true = apenas quem aceitou WhatsApp e não pediu descadastro (público apto a disparos) */
  messageable: z.boolean().optional(),
});

export type VoterFilters = z.infer<typeof voterFiltersSchema>;

/** Nome dos parâmetros de URL de cada filtro */
const PARAMS = {
  q: "q",
  neighborhoods: "bairro",
  cities: "cidade",
  registeredByIds: "cabo",
  coordinatorIds: "coord",
  genders: "genero",
  supportLevels: "apoio",
  sources: "origem",
  tags: "tag",
  electoralZones: "zona",
  ageMin: "idadeMin",
  ageMax: "idadeMax",
  createdFrom: "de",
  createdTo: "ate",
  hasGeo: "geo",
  messageable: "whatsapp",
} as const satisfies Record<keyof VoterFilters, string>;

type SearchParamsLike =
  | URLSearchParams
  | Record<string, string | string[] | undefined>;

function getAll(sp: SearchParamsLike, key: string): string[] {
  if (sp instanceof URLSearchParams) return sp.getAll(key).filter(Boolean);
  const v = sp[key];
  if (v === undefined) return [];
  return (Array.isArray(v) ? v : [v]).filter(Boolean);
}

/** Lê filtros da URL (searchParams da página ou URLSearchParams). Valores inválidos são ignorados. */
export function parseVoterFilters(sp: SearchParamsLike): VoterFilters {
  const raw: Record<string, unknown> = {};
  const q = getAll(sp, PARAMS.q)[0];
  if (q) raw.q = q;
  for (const key of [
    "neighborhoods",
    "cities",
    "registeredByIds",
    "coordinatorIds",
    "genders",
    "supportLevels",
    "sources",
    "tags",
    "electoralZones",
  ] as const) {
    const values = getAll(sp, PARAMS[key]);
    if (values.length) raw[key] = values;
  }
  for (const key of ["ageMin", "ageMax"] as const) {
    const v = getAll(sp, PARAMS[key])[0];
    if (v && /^\d+$/.test(v)) raw[key] = Number(v);
  }
  for (const key of ["createdFrom", "createdTo"] as const) {
    const v = getAll(sp, PARAMS[key])[0];
    if (v) raw[key] = v;
  }
  for (const key of ["hasGeo", "messageable"] as const) {
    const v = getAll(sp, PARAMS[key])[0];
    if (v === "1" || v === "true") raw[key] = true;
    if (v === "0" || v === "false") raw[key] = false;
  }
  // Valida campo a campo para descartar só o que for inválido
  const out: VoterFilters = {};
  const shape = voterFiltersSchema.shape;
  for (const [k, v] of Object.entries(raw)) {
    const parsed = shape[k as keyof VoterFilters].safeParse(v);
    if (parsed.success && parsed.data !== undefined) (out as Record<string, unknown>)[k] = parsed.data;
  }
  return out;
}

/** Converte filtros em URLSearchParams (para links e chamadas fetch) */
export function voterFiltersToSearchParams(filters: VoterFilters, base?: URLSearchParams): URLSearchParams {
  const sp = new URLSearchParams(base);
  for (const p of Object.values(PARAMS)) sp.delete(p);
  for (const [key, param] of Object.entries(PARAMS) as [keyof VoterFilters, string][]) {
    const v = filters[key];
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((item) => sp.append(param, String(item)));
    else if (typeof v === "boolean") sp.set(param, v ? "1" : "0");
    else sp.set(param, String(v));
  }
  return sp;
}

export function countActiveFilters(filters: VoterFilters): number {
  return Object.values(filters).filter((v) => v !== undefined && v !== "" && !(Array.isArray(v) && !v.length)).length;
}

/** Remove chaves vazias (útil antes de salvar em Broadcast.filters) */
export function cleanVoterFilters(filters: VoterFilters): VoterFilters {
  const out: VoterFilters = {};
  for (const [k, v] of Object.entries(filters)) {
    if (v === undefined || v === "" || (Array.isArray(v) && !v.length)) continue;
    (out as Record<string, unknown>)[k] = v;
  }
  return out;
}
