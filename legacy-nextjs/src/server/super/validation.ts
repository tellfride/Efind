// Validação dos formulários do super admin. Puro (sem banco) — usado pelas Server Actions e pelos testes.
import { z } from "zod";
import { CAMPAIGN_STATUSES, OFFICES, UFS } from "@/lib/constants";
import { passwordSchema } from "@/lib/password";
import { normalizeBrPhone } from "@/lib/phone";
import { DEFAULT_PRIMARY_COLOR, expectedBallotNumberLength } from "@/components/super/campaign-rules";

export { DEFAULT_PRIMARY_COLOR, expectedBallotNumberLength };

/** Credenciais exibidas uma única vez após criar usuário ou redefinir senha */
export interface IssuedCredentials {
  name: string;
  email: string;
  password: string;
  /** true quando a senha foi gerada pelo sistema (provisória) */
  generated: boolean;
  loginUrl: string;
}

/** Resultado da criação de campanha: credenciais do 1º administrador (exibidas uma única vez) */
export interface CreatedCampaign {
  campaignId: string;
  ballotName: string;
  credentials: IssuedCredentials;
}

type FieldErrors = Record<string, string[] | undefined>;

/** Campos vazios do formulário viram undefined (opcionais) */
const emptyToUndefined = (v: unknown) => (typeof v === "string" && v.trim() === "" ? undefined : v);

const optionalText = (max: number) =>
  z.preprocess(emptyToUndefined, z.string().trim().max(max, `Máximo de ${max} caracteres`).optional()).transform((v) => v ?? null);

export const idSchema = z.string().trim().min(1, "Identificador inválido").max(64, "Identificador inválido");

/** Dados do candidato/campanha (criação e edição) */
export const campaignFormSchema = z
  .object({
    candidateName: z
      .string({ required_error: "Informe o nome do candidato" })
      .trim()
      .min(3, "Informe o nome completo do candidato")
      .max(120, "Máximo de 120 caracteres"),
    ballotName: z
      .string({ required_error: "Informe o nome de urna" })
      .trim()
      .min(2, "Informe o nome de urna")
      .max(60, "Máximo de 60 caracteres"),
    ballotNumber: z
      .preprocess(emptyToUndefined, z.string().trim().regex(/^\d{2,5}$/, "Use de 2 a 5 dígitos").optional())
      .transform((v) => v ?? null),
    party: optionalText(30),
    office: z.enum(OFFICES, { errorMap: () => ({ message: "Selecione o cargo" }) }),
    city: optionalText(80),
    state: z
      .preprocess(emptyToUndefined, z.enum(UFS, { errorMap: () => ({ message: "Selecione uma UF válida" }) }).optional())
      .transform((v) => v ?? null),
    electionYear: z.preprocess(
      emptyToUndefined,
      z.coerce
        .number({ required_error: "Informe o ano da eleição", invalid_type_error: "Informe um ano válido" })
        .int("Informe um ano válido")
        .min(2000, "Informe um ano válido")
        .max(2100, "Informe um ano válido"),
    ),
    primaryColor: z
      .preprocess(
        emptyToUndefined,
        z
          .string()
          .trim()
          .regex(/^#[0-9a-fA-F]{6}$/, "Cor inválida (use o formato #RRGGBB)")
          .optional(),
      )
      .transform((v) => (v ?? DEFAULT_PRIMARY_COLOR).toLowerCase()),
    voterGoal: z
      .preprocess(
        emptyToUndefined,
        z.coerce
          .number({ invalid_type_error: "Informe um número" })
          .int("Informe um número inteiro")
          .min(1, "A meta deve ser maior que zero")
          .max(100_000_000, "Meta muito alta")
          .optional(),
      )
      .transform((v) => v ?? null),
  })
  .superRefine((data, ctx) => {
    const expected = expectedBallotNumberLength(data.office);
    if (data.ballotNumber && expected && data.ballotNumber.length !== expected) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["ballotNumber"],
        message: `Para este cargo o número de urna tem ${expected} dígitos`,
      });
    }
  });

export type CampaignFormData = z.infer<typeof campaignFormSchema>;

/** Conta de usuário criada pelo super admin (administrador de campanha ou super admin) */
export const accountFormSchema = z.object({
  name: z.string({ required_error: "Informe o nome" }).trim().min(3, "Informe o nome completo").max(120, "Máximo de 120 caracteres"),
  email: z
    .string({ required_error: "Informe o e-mail" })
    .trim()
    .toLowerCase()
    .email("Informe um e-mail válido")
    .max(160, "Máximo de 160 caracteres"),
  phone: z
    .preprocess(emptyToUndefined, z.string().trim().max(30, "Telefone inválido").optional())
    .refine((v) => !v || normalizeBrPhone(v) !== null, "Telefone inválido")
    .transform((v) => (v ? normalizeBrPhone(v) : null)),
  /** Vazio = o sistema gera uma senha provisória */
  password: z.preprocess(emptyToUndefined, passwordSchema.optional()).transform((v) => v ?? null),
});

export type AccountFormData = z.infer<typeof accountFormSchema>;

/** "name" + prefixo "admin" → "adminName" (campos do 1º administrador no formulário de criação) */
export function prefixFieldErrors(errors: FieldErrors, prefix: string): FieldErrors {
  const out: FieldErrors = {};
  for (const [key, value] of Object.entries(errors)) {
    out[`${prefix}${key.charAt(0).toUpperCase()}${key.slice(1)}`] = value;
  }
  return out;
}

export type CreateCampaignParse =
  | { success: true; data: { campaign: CampaignFormData; admin: AccountFormData } }
  | { success: false; fieldErrors: FieldErrors };

/** Formulário de criação: dados da campanha + primeiro administrador (campos adminName, adminEmail...) */
export function parseCreateCampaignInput(raw: Record<string, unknown>): CreateCampaignParse {
  const campaign = campaignFormSchema.safeParse(raw);
  const admin = accountFormSchema.safeParse({
    name: raw.adminName,
    email: raw.adminEmail,
    phone: raw.adminPhone,
    password: raw.adminPassword,
  });
  if (campaign.success && admin.success) {
    return { success: true, data: { campaign: campaign.data, admin: admin.data } };
  }
  return {
    success: false,
    fieldErrors: {
      ...(campaign.success ? {} : (campaign.error.flatten().fieldErrors as FieldErrors)),
      ...(admin.success ? {} : prefixFieldErrors(admin.error.flatten().fieldErrors as FieldErrors, "admin")),
    },
  };
}

export const campaignStatusSchema = z.object({
  campaignId: idSchema,
  status: z.enum(CAMPAIGN_STATUSES),
});

export const deleteCampaignSchema = z.object({
  campaignId: idSchema,
  confirmSlug: z.string({ required_error: "Digite o identificador da campanha" }).trim().min(1, "Digite o identificador da campanha"),
});

/** Campos alterados entre o registro atual e os dados validados (para a auditoria) */
export function changedFields<T extends Record<string, unknown>>(current: Partial<T>, next: T): string[] {
  return Object.keys(next).filter((k) => (current[k] ?? null) !== (next[k] ?? null));
}
