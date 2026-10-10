// Validação dos modelos de mensagem (servidor). Pura (zod), coberta pelos testes.
import { z } from "zod";
import { TEMPLATE_CATEGORIES, TEMPLATE_TYPES } from "@/lib/constants";
import { TEMPLATE_VARIABLES, type TemplateVariableKey } from "@/lib/template-vars";

export const TEMPLATE_BODY_MAX = 4096;

/** Nome de template aprovado da Meta/360dialog (minúsculas, números e _) ou ContentSid do Twilio (HX + 32 hex) */
export const PROVIDER_TEMPLATE_NAME_RE = /^(?:[a-z0-9_]{1,512}|HX[0-9a-fA-F]{32})$/;
/** Código de idioma do template (ex.: pt_BR, en_US, es) */
export const PROVIDER_LANGUAGE_RE = /^[a-z]{2,3}(?:_[A-Z]{2})?$/;

const variableKeys = TEMPLATE_VARIABLES.map((v) => v.key) as [TemplateVariableKey, ...TemplateVariableKey[]];

export function isHttpsUrl(value: string): boolean {
  try {
    const u = new URL(value);
    return u.protocol === "https:" && !!u.hostname;
  } catch {
    return false;
  }
}

const optionalText = (max: number) =>
  z
    .string()
    .trim()
    .max(max, `Use no máximo ${max} caracteres`)
    .optional()
    .nullable()
    .transform((v) => (v ? v : null));

export const templateInputSchema = z
  .object({
    name: z.string().trim().min(3, "Informe um nome com pelo menos 3 caracteres").max(120, "Use no máximo 120 caracteres"),
    category: z.enum(TEMPLATE_CATEGORIES, { errorMap: () => ({ message: "Escolha uma categoria" }) }),
    type: z.enum(TEMPLATE_TYPES, { errorMap: () => ({ message: "Escolha o tipo da mensagem" }) }),
    body: z
      .string()
      .transform((v) => v.replace(/\r\n?/g, "\n"))
      .refine((v) => v.trim().length > 0, "Escreva o texto da mensagem")
      .refine((v) => v.length <= TEMPLATE_BODY_MAX, `O texto pode ter no máximo ${TEMPLATE_BODY_MAX} caracteres`),
    mediaUrl: optionalText(1000),
    providerTemplateName: optionalText(512).refine(
      (v) => !v || PROVIDER_TEMPLATE_NAME_RE.test(v),
      "Use o nome exato do template aprovado (letras minúsculas, números e _) ou o ContentSid do Twilio (HX…)",
    ),
    providerTemplateLanguage: optionalText(10)
      .transform((v) => v ?? "pt_BR")
      .refine((v) => PROVIDER_LANGUAGE_RE.test(v), "Idioma inválido (ex.: pt_BR)"),
    providerVariables: z
      .array(z.enum(variableKeys, { errorMap: () => ({ message: "Variável desconhecida" }) }))
      .max(20, "Use no máximo 20 parâmetros")
      .default([]),
  })
  .superRefine((d, ctx) => {
    if (d.type === "TEXT") return;
    if (!d.mediaUrl) ctx.addIssue({ code: "custom", path: ["mediaUrl"], message: "Informe o link (https) da mídia" });
    else if (!isHttpsUrl(d.mediaUrl)) {
      ctx.addIssue({ code: "custom", path: ["mediaUrl"], message: "O link da mídia precisa ser um endereço https:// válido" });
    }
  })
  .transform((d) => ({ ...d, mediaUrl: d.type === "TEXT" ? null : d.mediaUrl }));

export type TemplateInput = z.infer<typeof templateInputSchema>;

/** Lê o JSON das variáveis do template oficial enviado pelo formulário (inválido → valor que falha na validação) */
export function parseVariablesField(raw: FormDataEntryValue | null): unknown {
  if (typeof raw !== "string" || !raw.trim()) return [];
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}
