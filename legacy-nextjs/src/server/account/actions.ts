"use server";

// Ações da própria conta (qualquer usuário logado, inclusive super admin).
import { z } from "zod";
import { prisma } from "@/lib/db";
import { createSession, getSessionUser } from "@/lib/auth";
import { hashPassword, passwordSchema, verifyPassword } from "@/lib/password";
import { audit } from "@/lib/audit";
import { actionError, actionOk, zodToActionError, type ActionResult } from "@/lib/action-result";
import { normalizeBrPhone } from "@/lib/phone";
import { revalidatePath } from "next/cache";

const changePasswordSchema = z
  .object({
    currentPassword: z.string().min(1, "Informe a senha atual"),
    newPassword: passwordSchema,
    confirmPassword: z.string(),
  })
  .refine((d) => d.newPassword === d.confirmPassword, { message: "As senhas não conferem", path: ["confirmPassword"] });

export async function changePasswordAction(_prev: ActionResult, formData: FormData): Promise<ActionResult> {
  const me = await getSessionUser();
  if (!me) return actionError("Sessão expirada. Faça login novamente.");
  const parsed = changePasswordSchema.safeParse(Object.fromEntries(formData));
  if (!parsed.success) return zodToActionError(parsed.error);

  const user = await prisma.user.findUnique({ where: { id: me.id } });
  if (!user || !(await verifyPassword(parsed.data.currentPassword, user.passwordHash))) {
    return actionError("Senha atual incorreta.", { currentPassword: ["Senha atual incorreta"] });
  }
  const updated = await prisma.user.update({
    where: { id: me.id },
    data: { passwordHash: await hashPassword(parsed.data.newPassword), sessionVersion: { increment: 1 } },
  });
  // Mantém esta sessão válida (as demais sessões são encerradas pelo incremento de sessionVersion)
  await createSession(updated.id, updated.sessionVersion);
  await audit({ action: "auth.password_change", campaignId: me.campaignId, userId: me.id });
  return actionOk("Senha alterada com sucesso.");
}

const profileSchema = z.object({
  name: z.string().trim().min(3, "Informe o nome completo").max(120),
  phone: z
    .string()
    .trim()
    .optional()
    .transform((v) => (v ? v : undefined))
    .refine((v) => !v || normalizeBrPhone(v) !== null, "Telefone inválido"),
});

export async function updateProfileAction(_prev: ActionResult, formData: FormData): Promise<ActionResult> {
  const me = await getSessionUser();
  if (!me) return actionError("Sessão expirada. Faça login novamente.");
  const parsed = profileSchema.safeParse(Object.fromEntries(formData));
  if (!parsed.success) return zodToActionError(parsed.error);
  await prisma.user.update({
    where: { id: me.id },
    data: { name: parsed.data.name, phone: parsed.data.phone ? normalizeBrPhone(parsed.data.phone) : null },
  });
  await audit({ action: "user.update", campaignId: me.campaignId, userId: me.id, entity: "User", entityId: me.id, details: { self: true } });
  revalidatePath("/", "layout");
  return actionOk("Perfil atualizado.");
}
