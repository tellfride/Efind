// Validação (zod) dos formulários de eleitor: público (/c/[code]) e painel (novo/editar).
// Puro: sem banco, testável. Entradas chegam como strings do FormData.
import { z } from "zod";
import {
  GENDERS,
  SUPPORT_LEVELS,
  UFS,
  type FormConfig,
  type FormFieldMode,
  type Gender,
  type SupportLevel,
} from "@/lib/constants";
import { normalizeBrPhone } from "@/lib/phone";
import { serializeTags, titleCase } from "@/lib/utils";
import {
  MAX_VOTER_AGE,
  MIN_VOTER_AGE,
  ageFromBirthDate,
  hasLetter,
  normalizeCepInput,
  parseBirthDateInput,
  smartCase,
} from "@/components/voters/voter-utils";

/** Primeiro valor textual (FormData pode repetir chaves) */
function firstString(v: unknown): string {
  if (Array.isArray(v)) return typeof v[0] === "string" ? v[0] : "";
  return typeof v === "string" ? v : "";
}

const rawString = z.preprocess(firstString, z.string());

function issue(ctx: z.RefinementCtx, message: string): never {
  ctx.addIssue({ code: z.ZodIssueCode.custom, message });
  return z.NEVER;
}

/**
 * Campo opcional/obrigatório/oculto conforme o modo. Vazio → null (ou erro se obrigatório);
 * oculto → sempre null (ignora o que vier do cliente).
 */
function modeField<T>(
  mode: FormFieldMode,
  requiredMessage: string,
  parse: (value: string, ctx: z.RefinementCtx) => T,
  max = 200,
) {
  return rawString.transform((raw, ctx): T | null => {
    if (mode === "hidden") return null;
    const v = raw.trim();
    if (!v) {
      if (mode === "required") issue(ctx, requiredMessage);
      return null;
    }
    if (v.length > max) return issue(ctx, `Use no máximo ${max} caracteres`);
    return parse(v, ctx);
  });
}

export const nameField = rawString.transform((raw, ctx) => {
  const v = raw.trim().replace(/\s+/g, " ");
  if (v.length < 3 || !hasLetter(v)) return issue(ctx, "Informe o nome completo");
  if (v.length > 120) return issue(ctx, "Nome muito longo (máx. 120 caracteres)");
  return titleCase(v);
});

export const phoneField = rawString.transform((raw, ctx) => {
  if (!raw.trim()) return issue(ctx, "Informe o WhatsApp com DDD");
  const phone = normalizeBrPhone(raw);
  return phone ?? issue(ctx, "Número inválido. Informe DDD + número, ex.: (11) 98765-4321");
});

export const emailField = (mode: FormFieldMode) =>
  modeField(
    mode,
    "Informe o e-mail",
    (v, ctx) => {
      const e = v.toLowerCase();
      return z.string().email().safeParse(e).success ? e : issue(ctx, "E-mail inválido");
    },
    160,
  );

export const birthDateField = (mode: FormFieldMode, now?: () => Date) =>
  modeField(mode, "Informe a data de nascimento", (v, ctx) => {
    const d = parseBirthDateInput(v);
    if (!d) return issue(ctx, "Data inválida. Use dd/mm/aaaa");
    const age = ageFromBirthDate(d, now ? now() : new Date());
    if (age === null || age < MIN_VOTER_AGE || age > MAX_VOTER_AGE) {
      return issue(ctx, `A idade deve estar entre ${MIN_VOTER_AGE} e ${MAX_VOTER_AGE} anos`);
    }
    return d;
  });

export const genderField = (mode: FormFieldMode) =>
  modeField<Gender>(mode, "Selecione uma opção", (v, ctx) =>
    (GENDERS as readonly string[]).includes(v) ? (v as Gender) : issue(ctx, "Opção inválida"),
  );

export const cepField = (mode: FormFieldMode) =>
  modeField(mode, "Informe o CEP", (v, ctx) => normalizeCepInput(v) ?? issue(ctx, "CEP inválido (8 dígitos)"));

export const ufField = (mode: FormFieldMode) =>
  modeField(mode, "Informe a UF", (v, ctx) => {
    const uf = v.toUpperCase();
    return (UFS as readonly string[]).includes(uf) ? uf : issue(ctx, "UF inválida");
  });

/** Texto livre com espaços normalizados */
export const textField = (mode: FormFieldMode, max: number, requiredMessage = "Campo obrigatório") =>
  modeField(mode, requiredMessage, (v) => v.replace(/\s+/g, " "), max);

/** Nome de lugar (rua, bairro, cidade) com capitalização uniforme */
export const placeField = (mode: FormFieldMode, max: number, requiredMessage: string) =>
  modeField(mode, requiredMessage, (v) => smartCase(v), max);

/** Zona (até 4 dígitos) e seção (até 5) sem zeros à esquerda */
export const digitsField = (mode: FormFieldMode, maxDigits: number, label: string) =>
  modeField(mode, `Informe a ${label}`, (v, ctx) =>
    new RegExp(`^\\d{1,${maxDigits}}$`).test(v) ? String(Number(v)) : issue(ctx, `${label[0].toUpperCase()}${label.slice(1)} inválida`),
  );

export const checkboxField = z.preprocess((v) => {
  const s = firstString(v);
  return s === "on" || s === "true" || s === "1";
}, z.boolean());

export const supportLevelField = modeField<SupportLevel>("optional", "", (v, ctx) =>
  (SUPPORT_LEVELS as readonly string[]).includes(v) ? (v as SupportLevel) : issue(ctx, "Nível de apoio inválido"),
);

export const tagsField = modeField("optional", "", (v) => serializeTags(v), 300);

export const notesField = modeField("optional", "", (v) => v.replace(/\r\n/g, "\n"), 2000);

/** Configuração de todos os grupos visíveis e opcionais (formulários do painel) */
export const PANEL_FORM_CONFIG: FormConfig = {
  email: "optional",
  birthDate: "optional",
  gender: "optional",
  address: "optional",
  electoral: "optional",
};

/** Campos pessoais/endereço comuns aos formulários, conforme a configuração dos grupos */
export function voterFieldsShape(config: FormConfig, now?: () => Date) {
  const address = config.address;
  // Endereço obrigatório = CEP, bairro, cidade e UF (rua, número e complemento continuam opcionais)
  const addressOptional: FormFieldMode = address === "hidden" ? "hidden" : "optional";
  return {
    name: nameField,
    phone: phoneField,
    email: emailField(config.email),
    birthDate: birthDateField(config.birthDate, now),
    gender: genderField(config.gender),
    cep: cepField(address),
    street: placeField(addressOptional, 160, "Informe a rua"),
    number: textField(addressOptional, 20),
    complement: textField(addressOptional, 80),
    neighborhood: placeField(address, 100, "Informe o bairro"),
    city: placeField(address, 100, "Informe a cidade"),
    state: ufField(address),
    electoralZone: digitsField(config.electoral, 4, "zona eleitoral"),
    electoralSection: digitsField(config.electoral, 5, "seção eleitoral"),
  };
}

const PUBLIC_SOURCES = ["LINK", "QRCODE"] as const;

/** Formulário público de cadastro (link/QR Code) */
export function buildPublicFormSchema(config: FormConfig, now?: () => Date) {
  return z.object({
    ...voterFieldsShape(config, now),
    consent: checkboxField.refine((v) => v, "Para concluir o cadastro, autorize o uso dos seus dados"),
    whatsappOptIn: checkboxField,
    source: z.preprocess(firstString, z.enum(PUBLIC_SOURCES).catch("LINK")),
  });
}
export type PublicFormData = z.output<ReturnType<typeof buildPublicFormSchema>>;

/** Cadastro manual no painel */
export function buildVoterCreateSchema(now?: () => Date) {
  return z.object({
    ...voterFieldsShape(PANEL_FORM_CONFIG, now),
    supportLevel: supportLevelField,
    tags: tagsField,
    notes: notesField,
    registeredById: rawString.transform((v) => v.trim().slice(0, 64) || null),
    consent: checkboxField.refine((v) => v, "Confirme que o eleitor autorizou o uso dos dados"),
    whatsappOptIn: checkboxField,
  });
}
export type VoterCreateData = z.output<ReturnType<typeof buildVoterCreateSchema>>;

/** Edição no painel (consentimento e "cadastrado por" têm ações próprias) */
export function buildVoterUpdateSchema(now?: () => Date) {
  return z.object({
    id: rawString.pipe(z.string().trim().min(1, "Eleitor inválido").max(64)),
    ...voterFieldsShape(PANEL_FORM_CONFIG, now),
    supportLevel: supportLevelField,
    tags: tagsField,
    notes: notesField,
  });
}
export type VoterUpdateData = z.output<ReturnType<typeof buildVoterUpdateSchema>>;

/** Campos do eleitor gravados no banco a partir dos formulários */
export const VOTER_FIELD_KEYS = [
  "name",
  "phone",
  "email",
  "birthDate",
  "gender",
  "cep",
  "street",
  "number",
  "complement",
  "neighborhood",
  "city",
  "state",
  "electoralZone",
  "electoralSection",
] as const;
export type VoterFieldKey = (typeof VOTER_FIELD_KEYS)[number];
export type VoterFieldsData = Pick<PublicFormData, VoterFieldKey>;

export function pickVoterFields<T extends VoterFieldsData>(data: T): VoterFieldsData {
  const out = {} as Record<VoterFieldKey, unknown>;
  for (const k of VOTER_FIELD_KEYS) out[k] = data[k];
  return out as VoterFieldsData;
}
