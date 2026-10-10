// Validação das configurações da campanha (puro: sem banco, sem next/*) — testado em tests/settings*.test.ts.
import { z } from "zod";
import { OFFICES, UFS, type FormConfig } from "@/lib/constants";
import {
  FORM_FIELD_GROUPS,
  FORM_FIELD_MODES,
  HEX_COLOR_REGEX,
  SETTINGS_LIMITS as L,
  validateLogoDataUrl,
} from "@/components/settings/settings-rules";

/** Texto opcional: espaços extras removidos; vazio vira null */
function optionalText(max: number, tooLong: string) {
  return z.preprocess(
    (v) => {
      if (typeof v !== "string") return v ?? null;
      const t = v.trim();
      return t === "" ? null : t;
    },
    z.string().max(max, tooLong).nullable(),
  );
}

/** Inteiro opcional digitado com ou sem separador de milhar ("10.000") */
function optionalInt(min: number, max: number, message: string) {
  return z.preprocess(
    (v) => {
      if (v === null || v === undefined) return null;
      const digits = String(v).replace(/[.\s]/g, "").trim();
      if (digits === "") return null;
      return /^\d+$/.test(digits) ? Number(digits) : Number.NaN;
    },
    z.number({ invalid_type_error: message }).int(message).min(min, message).max(max, message).nullable(),
  );
}

export const hexColorSchema = z
  .string({ required_error: "Informe a cor principal" })
  .trim()
  .regex(HEX_COLOR_REGEX, "Use o formato hexadecimal #RRGGBB (ex.: #4f46e5)")
  .transform((v) => v.toLowerCase());

export const formFieldModeSchema = z.enum(FORM_FIELD_MODES, {
  errorMap: () => ({ message: "Escolha oculto, opcional ou obrigatório" }),
});

export const formConfigSchema = z
  .object({
    email: formFieldModeSchema,
    birthDate: formFieldModeSchema,
    gender: formFieldModeSchema,
    address: formFieldModeSchema,
    electoral: formFieldModeSchema,
  })
  .strict() satisfies z.ZodType<FormConfig>;

export const LOGO_ACTIONS = ["keep", "remove", "replace"] as const;
export type LogoAction = (typeof LOGO_ACTIONS)[number];

export const identitySchema = z
  .object({
    candidateName: z
      .string({ required_error: "Informe o nome do candidato" })
      .trim()
      .min(3, "Informe o nome completo do candidato")
      .max(L.candidateName, `Máximo de ${L.candidateName} caracteres`),
    ballotName: z
      .string({ required_error: "Informe o nome de urna" })
      .trim()
      .min(2, "Informe o nome de urna")
      .max(L.ballotName, `Máximo de ${L.ballotName} caracteres`),
    ballotNumber: z.preprocess(
      (v) => (typeof v === "string" ? v.replace(/\D/g, "") || null : (v ?? null)),
      z.string().regex(/^\d{2,5}$/, "O número de urna tem de 2 a 5 dígitos").nullable(),
    ),
    party: optionalText(L.party, `Máximo de ${L.party} caracteres`),
    office: z.enum(OFFICES, { errorMap: () => ({ message: "Escolha o cargo disputado" }) }),
    city: optionalText(L.city, `Máximo de ${L.city} caracteres`),
    state: z.preprocess(
      (v) => (typeof v === "string" && v.trim() !== "" ? v.trim().toUpperCase() : null),
      z.enum(UFS, { errorMap: () => ({ message: "Escolha uma UF válida" }) }).nullable(),
    ),
    electionYear: z.preprocess(
      (v) => (typeof v === "string" ? (v.trim() === "" ? undefined : Number(v.trim())) : v),
      z
        .number({ required_error: "Informe o ano da eleição", invalid_type_error: "Ano inválido" })
        .int("Ano inválido")
        .min(L.electionYearMin, "Ano inválido")
        .max(L.electionYearMax, "Ano inválido"),
    ),
    voterGoal: optionalInt(1, L.voterGoalMax, "Informe uma meta entre 1 e 10.000.000"),
    primaryColor: hexColorSchema,
    logoAction: z.enum(LOGO_ACTIONS).default("keep"),
    logoDataUrl: z.string().optional(),
  })
  .superRefine((data, ctx) => {
    if (data.logoAction !== "replace") return;
    const result = validateLogoDataUrl(data.logoDataUrl ?? "");
    if (!result.ok) ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["logo"], message: result.error });
  });

export type IdentityInput = z.infer<typeof identitySchema>;

export const publicFormSchema = z.object({
  formTitle: optionalText(L.formTitle, `Máximo de ${L.formTitle} caracteres`),
  formMessage: optionalText(L.formMessage, `Máximo de ${L.formMessage} caracteres`),
  formConfig: formConfigSchema,
  consentText: optionalText(L.consentTextMax, `Máximo de ${L.consentTextMax} caracteres`).refine(
    (v) => v === null || v.length >= L.consentTextMin,
    `O texto de consentimento deve ter pelo menos ${L.consentTextMin} caracteres (ou deixe em branco para usar o padrão)`,
  ),
  privacyContact: optionalText(L.privacyContact, `Máximo de ${L.privacyContact} caracteres`),
});

export type PublicFormInput = z.infer<typeof publicFormSchema>;

function str(fd: FormData, key: string): string | undefined {
  const v = fd.get(key);
  return typeof v === "string" ? v : undefined;
}

/** Monta o objeto bruto do cartão "Identidade da campanha" a partir do FormData */
export function identityInputFromFormData(fd: FormData): Record<string, unknown> {
  const keys = [
    "candidateName",
    "ballotName",
    "ballotNumber",
    "party",
    "office",
    "city",
    "state",
    "electionYear",
    "voterGoal",
    "primaryColor",
    "logoAction",
    "logoDataUrl",
  ];
  return Object.fromEntries(keys.map((k) => [k, str(fd, k)]));
}

/** Nome do campo do modo de cada grupo do formulário público (ex.: "formConfig.email") */
export function formConfigFieldName(key: keyof FormConfig): string {
  return `formConfig.${key}`;
}

/** Monta o objeto bruto do cartão "Formulário público" a partir do FormData */
export function publicFormInputFromFormData(fd: FormData): Record<string, unknown> {
  const formConfig = Object.fromEntries(FORM_FIELD_GROUPS.map((g) => [g.key, str(fd, formConfigFieldName(g.key))]));
  return {
    formTitle: str(fd, "formTitle"),
    formMessage: str(fd, "formMessage"),
    formConfig,
    consentText: str(fd, "consentText"),
    privacyContact: str(fd, "privacyContact"),
  };
}

/** Converte os erros do zod em fieldErrors planos (formConfig.email → "formConfig.email") */
export function flattenIssues(error: z.ZodError): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const issue of error.issues) {
    const key = issue.path.length ? issue.path.join(".") : "_form";
    (out[key] ??= []).push(issue.message);
  }
  return out;
}

// ---------- Diferença entre versões (para a auditoria) ----------

function normalizeForCompare(value: unknown): unknown {
  if (value === undefined || value === null || value === "") return null;
  if (value instanceof Date) return value.getTime();
  if (Array.isArray(value)) return value.map(normalizeForCompare);
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    return Object.fromEntries(
      Object.keys(obj)
        .sort()
        .map((k) => [k, normalizeForCompare(obj[k])]),
    );
  }
  return value;
}

/** Igualdade estrutural (null/undefined/"" equivalentes; ordem das chaves irrelevante) */
export function sameValue(a: unknown, b: unknown): boolean {
  return JSON.stringify(normalizeForCompare(a)) === JSON.stringify(normalizeForCompare(b));
}

/** Nomes dos campos de `next` cujo valor difere de `prev` (somente nomes — nunca valores) */
export function changedFields<T extends Record<string, unknown>>(
  prev: Readonly<Record<string, unknown>>,
  next: T,
): (keyof T & string)[] {
  return (Object.keys(next) as (keyof T & string)[]).filter((k) => !sameValue(prev[k], next[k]));
}
