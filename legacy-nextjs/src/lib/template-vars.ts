// Variáveis disponíveis nos modelos de mensagem e renderização. Puro (usado no cliente para pré-visualização).
import { firstName } from "./utils";

export const TEMPLATE_VARIABLES = [
  { key: "nome", label: "Nome completo do eleitor", example: "Maria Aparecida da Silva" },
  { key: "primeiro_nome", label: "Primeiro nome do eleitor", example: "Maria" },
  { key: "bairro", label: "Bairro do eleitor", example: "Centro" },
  { key: "cidade", label: "Cidade do eleitor", example: "Campinas" },
  { key: "candidato", label: "Nome de urna do candidato", example: "Dr. João" },
  { key: "numero", label: "Número do candidato", example: "12345" },
  { key: "partido", label: "Partido", example: "PXX" },
  { key: "cargo", label: "Cargo disputado", example: "Vereador(a)" },
  { key: "cabo", label: "Nome de quem cadastrou o eleitor", example: "Carlos" },
] as const;

export type TemplateVariableKey = (typeof TEMPLATE_VARIABLES)[number]["key"];
export type TemplateContext = Partial<Record<TemplateVariableKey, string | null | undefined>>;

const VAR_REGEX = /\{\{\s*([a-zA-Z_]+)\s*\}\}/g;

/** Substitui {{variavel}} pelo valor do contexto (variável desconhecida/vazia vira "") */
export function renderTemplate(body: string, ctx: TemplateContext): string {
  return body.replace(VAR_REGEX, (_, raw: string) => {
    const key = raw.toLowerCase() as TemplateVariableKey;
    const v = ctx[key];
    return v === null || v === undefined ? "" : String(v);
  });
}

/** Variáveis usadas num texto (na ordem de aparição, sem repetição) */
export function extractVariables(body: string): string[] {
  const out: string[] = [];
  for (const m of body.matchAll(VAR_REGEX)) {
    const k = m[1].toLowerCase();
    if (!out.includes(k)) out.push(k);
  }
  return out;
}

export function unknownVariables(body: string): string[] {
  const known = new Set<string>(TEMPLATE_VARIABLES.map((v) => v.key));
  return extractVariables(body).filter((k) => !known.has(k));
}

export const EXAMPLE_CONTEXT: TemplateContext = Object.fromEntries(
  TEMPLATE_VARIABLES.map((v) => [v.key, v.example]),
) as TemplateContext;

export interface TemplateContextSource {
  voter: { name: string; neighborhood?: string | null; city?: string | null };
  campaign: { ballotName: string; ballotNumber?: string | null; party?: string | null; officeLabel?: string | null };
  registeredBy?: { name: string } | null;
}

export function buildTemplateContext(src: TemplateContextSource): TemplateContext {
  return {
    nome: src.voter.name,
    primeiro_nome: firstName(src.voter.name),
    bairro: src.voter.neighborhood ?? "",
    cidade: src.voter.city ?? "",
    candidato: src.campaign.ballotName,
    numero: src.campaign.ballotNumber ?? "",
    partido: src.campaign.party ?? "",
    cargo: src.campaign.officeLabel ?? "",
    cabo: src.registeredBy ? firstName(src.registeredBy.name) : "",
  };
}
