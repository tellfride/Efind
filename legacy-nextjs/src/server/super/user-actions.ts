"use server";

// Ações sobre as contas de super admin da plataforma.
import { revalidatePath } from "next/cache";
import { z } from "zod";
import { prisma } from "@/lib/db";
import { authorizeSuperAdmin } from "@/lib/auth";
import { audit } from "@/lib/audit";
import { appUrl } from "@/lib/env";
import { generateTempPassword, hashPassword } from "@/lib/password";
import { actionError, actionOk, formDataToObject, zodToActionError, type ActionResult } from "@/lib/action-result";
import { emailInUse, isUniqueViolation, safeErrorTag, uniqueInviteCode } from "./accounts";
import { accountFormSchema, idSchema, type IssuedCredentials } from "./validation";

const EMAIL_TAKEN = "Este e-mail já está cadastrado no E-Find. Use outro.";

export async function createSuperUserAction(
  _prev: ActionResult<IssuedCredentials>,
  formData: FormData,
): Promise<ActionResult<IssuedCredentials>> {
  const auth = await authorizeSuperAdmin();
  if (!auth.ok) return actionError(auth.error);
  const parsed = accountFormSchema.safeParse(formDataToObject(formData));
  if (!parsed.success) return zodToActionError(parsed.error);
  const data = parsed.data;
  if (await emailInUse(data.email)) return actionError(EMAIL_TAKEN, { email: [EMAIL_TAKEN] });

  const password = data.password ?? generateTempPassword();
  let userId: string;
  try {
    const user = await prisma.user.create({
      data: {
        campaignId: null,
        name: data.name,
        email: data.email,
        phone: data.phone,
        passwordHash: await hashPassword(password),
        role: "SUPER_ADMIN",
        inviteCode: await uniqueInviteCode(prisma, 10),
      },
      select: { id: true },
    });
    userId = user.id;
  } catch (err) {
    if (isUniqueViolation(err, "email")) return actionError(EMAIL_TAKEN, { email: [EMAIL_TAKEN] });
    console.error("[super] falha ao criar super admin:", safeErrorTag(err));
    return actionError("Não foi possível criar o usuário. Tente novamente.");
  }

  await audit({
    action: "user.create",
    campaignId: null,
    userId: auth.user.id,
    entity: "User",
    entityId: userId,
    details: { role: "SUPER_ADMIN", email: data.email, passwordGenerated: !data.password },
  });
  revalidatePath("/super/usuarios");
  return actionOk("Super admin criado.", {
    name: data.name,
    email: data.email,
    password,
    generated: !data.password,
    loginUrl: appUrl("/login"),
  });
}

const targetSchema = z.object({ userId: idSchema });

export async function setSuperUserActiveAction(input: { userId: string; active: boolean }): Promise<ActionResult> {
  const auth = await authorizeSuperAdmin();
  if (!auth.ok) return actionError(auth.error);
  const parsed = targetSchema.extend({ active: z.boolean() }).safeParse(input);
  if (!parsed.success) return actionError("Dados inválidos.");
  const { userId, active } = parsed.data;

  if (!active && userId === auth.user.id) return actionError("Você não pode desativar a sua própria conta.");

  const user = await prisma.user.findFirst({ where: { id: userId, role: "SUPER_ADMIN" }, select: { id: true, active: true } });
  if (!user) return actionError("Usuário não encontrado.");
  if (user.active === active) return actionOk(active ? "O usuário já está ativo." : "O usuário já está desativado.");

  if (!active) {
    const others = await prisma.user.count({ where: { role: "SUPER_ADMIN", active: true, id: { not: user.id } } });
    if (others === 0) return actionError("A plataforma precisa de pelo menos um super admin ativo.");
  }

  await prisma.user.update({
    where: { id: user.id },
    data: active ? { active: true } : { active: false, sessionVersion: { increment: 1 } },
  });
  await audit({
    action: active ? "user.activate" : "user.deactivate",
    campaignId: null,
    userId: auth.user.id,
    entity: "User",
    entityId: user.id,
    details: { role: "SUPER_ADMIN" },
  });
  revalidatePath("/super/usuarios");
  return actionOk(active ? "Super admin reativado." : "Super admin desativado. As sessões dele foram encerradas.");
}

export async function resetSuperUserPasswordAction(input: { userId: string }): Promise<ActionResult<IssuedCredentials>> {
  const auth = await authorizeSuperAdmin();
  if (!auth.ok) return actionError(auth.error);
  const parsed = targetSchema.safeParse(input);
  if (!parsed.success) return actionError("Dados inválidos.");
  if (parsed.data.userId === auth.user.id) {
    return actionError("Para trocar a sua própria senha, use a página Meu perfil.");
  }

  const user = await prisma.user.findFirst({
    where: { id: parsed.data.userId, role: "SUPER_ADMIN" },
    select: { id: true, name: true, email: true },
  });
  if (!user) return actionError("Usuário não encontrado.");

  const password = generateTempPassword();
  await prisma.user.update({
    where: { id: user.id },
    data: { passwordHash: await hashPassword(password), sessionVersion: { increment: 1 } },
  });
  await audit({
    action: "user.password_reset",
    campaignId: null,
    userId: auth.user.id,
    entity: "User",
    entityId: user.id,
    details: { role: "SUPER_ADMIN" },
  });
  revalidatePath("/super/usuarios");
  return actionOk("Senha redefinida. As sessões abertas desse usuário foram encerradas.", {
    name: user.name,
    email: user.email,
    password,
    generated: true,
    loginUrl: appUrl("/login"),
  });
}
