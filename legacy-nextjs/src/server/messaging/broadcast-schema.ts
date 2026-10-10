// Validação do formulário de criação de disparo (servidor). Pura (zod).
import { z } from "zod";
import { voterFiltersSchema } from "@/lib/voter-filters";

export const broadcastInputSchema = z
  .object({
    name: z.string().trim().min(3, "Dê um nome com pelo menos 3 caracteres").max(120, "Use no máximo 120 caracteres"),
    templateId: z.string().trim().min(1, "Escolha o modelo de mensagem").max(64),
    connectionId: z.string().trim().min(1, "Escolha a conexão de WhatsApp").max(64),
    ratePerMinute: z.coerce
      .number({ invalid_type_error: "Informe a velocidade de envio" })
      .int("Use um número inteiro")
      .min(1, "Mínimo de 1 mensagem por minuto")
      .max(1000, "Velocidade muito alta"),
    mode: z.enum(["now", "schedule"], { errorMap: () => ({ message: "Escolha quando enviar" }) }),
    scheduledAt: z.string().trim().max(32).optional(),
    filters: voterFiltersSchema,
    consent: z.literal("on", { errorMap: () => ({ message: "Confirme o consentimento dos destinatários" }) }),
  })
  .strict();

export type BroadcastInput = z.infer<typeof broadcastInputSchema>;

/** JSON dos filtros enviado pelo assistente (inválido → valor que falha na validação) */
export function parseFiltersField(raw: FormDataEntryValue | null): unknown {
  if (typeof raw !== "string" || !raw.trim()) return {};
  try {
    const value: unknown = JSON.parse(raw);
    return value && typeof value === "object" && !Array.isArray(value) ? value : null;
  } catch {
    return null;
  }
}
