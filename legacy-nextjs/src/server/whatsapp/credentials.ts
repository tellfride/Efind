// Validação, normalização e mascaramento das credenciais dos provedores (funções puras).
// Segredos nunca voltam ao navegador: a interface recebe apenas a versão mascarada.
import { maskSecret } from "@/lib/crypto";
import type { WhatsAppProviderKey } from "@/lib/constants";
import type { ProviderDefinition, ProviderField } from "./types";

/** Prefixos dos campos de credenciais no FormData do assistente */
export const CREDENTIAL_FIELD_PREFIX = "cred.";
export const CLEAR_FIELD_PREFIX = "clear.";

const MAX_CREDENTIAL_LENGTH = 4096;

/** Dados de um provedor que podem ir ao navegador (sem funções) */
export interface ProviderInfo {
  key: WhatsAppProviderKey;
  label: string;
  description: string;
  official: boolean;
  docsUrl?: string;
  setupSteps: string[];
  fields: ProviderField[];
  requiresApprovedTemplate: boolean;
  /** Provedor usa o handshake de verificação da Meta (verify token) */
  usesVerifyToken: boolean;
}

export function toProviderInfo(def: ProviderDefinition): ProviderInfo {
  return {
    key: def.key,
    label: def.label,
    description: def.description,
    official: def.official,
    docsUrl: def.docsUrl,
    setupSteps: [...def.setupSteps],
    fields: def.fields.map((f) => ({ ...f })),
    requiresApprovedTemplate: def.requiresApprovedTemplate,
    usesVerifyToken: typeof def.handleVerification === "function",
  };
}

type RuleResult = { value: string } | { error: string };
type Rule = (value: string) => RuleResult;

const noSpaces = (label: string, min: number): Rule => (v) =>
  /\s/.test(v) ? { error: `${label} não pode conter espaços` } : v.length < min ? { error: `${label} parece incompleto` } : { value: v };

const httpsUrl: Rule = (v) => {
  try {
    const u = new URL(v);
    if (u.protocol !== "https:") return { error: "Use uma URL que comece com https://" };
    return { value: u.href.replace(/\/+$/, "") };
  } catch {
    return { error: "URL inválida" };
  }
};

/** Regras específicas por provedor (valor já aparado e não vazio) */
const FIELD_RULES: Partial<Record<WhatsAppProviderKey, Record<string, Rule>>> = {
  META_CLOUD: {
    phoneNumberId: (v) => (/^\d{5,25}$/.test(v) ? { value: v } : { error: "Informe apenas os números do ID" }),
    businessAccountId: (v) => (/^\d{5,25}$/.test(v) ? { value: v } : { error: "Informe apenas os números do ID" }),
    accessToken: noSpaces("O token", 20),
    appSecret: noSpaces("A chave secreta", 16),
    apiVersion: (v) => {
      const normalized = v.toLowerCase().startsWith("v") ? v.toLowerCase() : `v${v}`;
      return /^v\d{1,2}\.\d$/.test(normalized) ? { value: normalized } : { error: "Use o formato v21.0" };
    },
  },
  DIALOG360: {
    apiKey: noSpaces("A chave de API", 10),
    baseUrl: httpsUrl,
  },
  TWILIO: {
    accountSid: (v) => (/^AC[0-9a-fA-F]{32}$/.test(v) ? { value: v } : { error: "O Account SID começa com AC e tem 34 caracteres" }),
    authToken: noSpaces("O Auth Token", 16),
    fromNumber: (v) => {
      const digits = v.replace(/^whatsapp:/i, "").replace(/[\s().-]/g, "");
      return /^\+?\d{10,15}$/.test(digits)
        ? { value: `+${digits.replace(/^\+/, "")}` }
        : { error: "Use o formato internacional, ex.: +5511999999999" };
    },
    messagingServiceSid: (v) =>
      /^MG[0-9a-fA-F]{32}$/.test(v) ? { value: v } : { error: "O Messaging Service SID começa com MG e tem 34 caracteres" },
  },
  SANDBOX: {
    failureRate: (v) => {
      const n = Number(v.replace(",", "."));
      if (!Number.isFinite(n) || n < 0 || n > 0.5) return { error: "Informe um valor entre 0 e 0,5" };
      return { value: String(n) };
    },
  },
};

const genericUrl: Rule = (v) => {
  try {
    const u = new URL(v);
    return u.protocol === "https:" || u.protocol === "http:" ? { value: v } : { error: "URL inválida" };
  } catch {
    return { error: "URL inválida" };
  }
};

export type ResolveCredentialsResult =
  | { ok: true; credentials: Record<string, string>; changed: string[] }
  | { ok: false; fieldErrors: Record<string, string[]> };

/**
 * Valida e normaliza as credenciais digitadas.
 * - Segredos em branco mantêm o valor salvo (edição); `clear` remove segredos opcionais.
 * - Campos não declarados pelo provedor são descartados.
 * - fieldErrors usa as chaves do formulário ("cred.<campo>").
 * - changed lista os NOMES dos campos alterados (nunca os valores).
 */
export function resolveCredentials(
  def: Pick<ProviderDefinition, "key" | "fields">,
  input: Record<string, string | null | undefined>,
  existing: Record<string, string> = {},
  clear: string[] = [],
): ResolveCredentialsResult {
  const credentials: Record<string, string> = {};
  const fieldErrors: Record<string, string[]> = {};
  const rules = FIELD_RULES[def.key] ?? {};

  for (const field of def.fields) {
    const key = `${CREDENTIAL_FIELD_PREFIX}${field.name}`;
    const raw = String(input[field.name] ?? "").trim();
    if (raw.length > MAX_CREDENTIAL_LENGTH) {
      fieldErrors[key] = ["Valor muito longo"];
      continue;
    }
    if (!raw) {
      const previous = existing[field.name];
      if (field.secret && previous && !(clear.includes(field.name) && !field.required)) {
        credentials[field.name] = previous;
      } else if (field.required) {
        fieldErrors[key] = [field.secret ? "Informe este segredo" : "Campo obrigatório"];
      }
      continue;
    }
    const rule = rules[field.name] ?? (field.type === "url" ? genericUrl : undefined);
    const res: RuleResult = rule ? rule(raw) : { value: raw };
    if ("error" in res) fieldErrors[key] = [res.error];
    else credentials[field.name] = res.value;
  }

  if (Object.keys(fieldErrors).length) return { ok: false, fieldErrors };
  const changed = def.fields
    .map((f) => f.name)
    .filter((name) => (credentials[name] ?? "") !== (existing[name] ?? ""));
  return { ok: true, credentials, changed };
}

/** Separa credenciais em valores visíveis (campos comuns) e segredos mascarados */
export function splitCredentials(
  fields: ProviderField[],
  credentials: Record<string, string>,
): { values: Record<string, string>; secrets: Record<string, string> } {
  const values: Record<string, string> = {};
  const secrets: Record<string, string> = {};
  for (const f of fields) {
    const v = credentials[f.name];
    if (!v) continue;
    if (f.secret) secrets[f.name] = maskSecret(v);
    else values[f.name] = v;
  }
  return { values, secrets };
}

/** Garante que o objeto descriptografado seja um mapa de strings */
export function sanitizeCredentialObject(value: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  if (!value || typeof value !== "object" || Array.isArray(value)) return out;
  for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
    if (typeof v === "string") out[k] = v;
    else if (typeof v === "number" || typeof v === "boolean") out[k] = String(v);
  }
  return out;
}
