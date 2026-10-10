// Leitura de filtros da URL das telas do super admin e saneamento de detalhes da auditoria.
// Puro (sem banco) — testável.
import { CAMPAIGN_STATUSES, type CampaignStatus } from "@/lib/constants";

type SearchParams = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value)?.trim() ?? "";
}

function parsePositiveInt(value: string): number {
  const n = Number(value);
  return Number.isInteger(n) && n > 0 ? n : 1;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function isValidIsoDate(value: string): boolean {
  if (!ISO_DATE.test(value)) return false;
  const d = new Date(`${value}T12:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === value;
}

// ---------- Lista de campanhas ----------

export interface CampaignListParams {
  q: string;
  status: CampaignStatus | "";
  page: number;
}

export function parseCampaignListParams(sp: SearchParams): CampaignListParams {
  const status = first(sp.status);
  return {
    q: first(sp.q).slice(0, 100),
    status: (CAMPAIGN_STATUSES as readonly string[]).includes(status) ? (status as CampaignStatus) : "",
    page: parsePositiveInt(first(sp.page)),
  };
}

// ---------- Auditoria ----------

/** Valor do filtro de campanha para eventos sem campanha (plataforma) */
export const PLATFORM_SCOPE = "plataforma";

export interface AuditFilterParams {
  /** "" = todas; PLATFORM_SCOPE = só eventos da plataforma; senão id da campanha */
  campaign: string;
  action: string;
  /** yyyy-mm-dd (inclusive) */
  from: string;
  to: string;
  page: number;
}

export function parseAuditFilterParams(sp: SearchParams): AuditFilterParams {
  const campaign = first(sp.campanha);
  const action = first(sp.acao);
  const from = first(sp.de);
  const to = first(sp.ate);
  return {
    campaign: /^[\w-]{1,64}$/.test(campaign) ? campaign : "",
    action: /^[a-z0-9_.]{1,64}$/i.test(action) ? action : "",
    from: isValidIsoDate(from) ? from : "",
    to: isValidIsoDate(to) ? to : "",
    page: parsePositiveInt(first(sp.page)),
  };
}

/** Intervalo de datas no fuso de Brasília (UTC-3). Datas invertidas são trocadas. */
export function auditDateRange(from: string, to: string): { gte?: Date; lte?: Date } | null {
  let start = from;
  let end = to;
  if (start && end && start > end) [start, end] = [end, start];
  const range: { gte?: Date; lte?: Date } = {};
  if (start) range.gte = new Date(`${start}T00:00:00.000-03:00`);
  if (end) range.lte = new Date(`${end}T23:59:59.999-03:00`);
  return range.gte || range.lte ? range : null;
}

/** Converte os filtros de volta para parâmetros de URL (paginação mantém os filtros) */
export function auditFilterSearchParams(f: AuditFilterParams): Record<string, string> {
  const out: Record<string, string> = {};
  if (f.campaign) out.campanha = f.campaign;
  if (f.action) out.acao = f.action;
  if (f.from) out.de = f.from;
  if (f.to) out.ate = f.to;
  return out;
}

/**
 * O super admin nunca vê dados pessoais de eleitores. Em eventos relativos a eleitores
 * (voter.*, mensagens, opt-out), chaves com dados pessoais são mascaradas nos detalhes.
 */
const VOTER_ENTITIES = new Set(["voter", "broadcastmessage", "inboundmessage"]);
const PERSONAL_KEYS = new Set(
  [
    "name",
    "nome",
    "fullname",
    "phone",
    "telefone",
    "celular",
    "whatsapp",
    "email",
    "cpf",
    "rg",
    "birthdate",
    "nascimento",
    "street",
    "rua",
    "logradouro",
    "number",
    "numero",
    "complement",
    "complemento",
    "address",
    "endereco",
    "cep",
    "latitude",
    "longitude",
    "lat",
    "lng",
    "notes",
    "observacoes",
    "body",
    "renderedbody",
    "fromphone",
    "electoralzone",
    "electoralsection",
    "consentip",
  ].map((k) => k.toLowerCase()),
);
export const REDACTED = "•••";

export function isVoterRelatedAudit(action: string, entity: string | null | undefined): boolean {
  return action.startsWith("voter.") || VOTER_ENTITIES.has((entity ?? "").toLowerCase());
}

/** Valores que parecem telefone ou e-mail, mesmo sob chaves desconhecidas */
function looksPersonal(value: string): boolean {
  if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim())) return true;
  const digits = value.replace(/\D/g, "");
  return /^[+\d\s().-]+$/.test(value.trim()) && digits.length >= 10 && digits.length <= 13;
}

function redact(value: unknown, depth = 0): unknown {
  if (depth > 6) return REDACTED;
  if (typeof value === "string") return looksPersonal(value) ? REDACTED : value;
  if (Array.isArray(value)) return value.map((v) => redact(v, depth + 1));
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = PERSONAL_KEYS.has(k.toLowerCase()) ? REDACTED : redact(v, depth + 1);
    }
    return out;
  }
  return value;
}

/** Detalhes da auditoria prontos para exibição ao super admin */
export function sanitizeAuditDetails(action: string, entity: string | null | undefined, details: unknown): unknown {
  if (details === null || details === undefined) return null;
  return isVoterRelatedAudit(action, entity) ? redact(details) : details;
}
