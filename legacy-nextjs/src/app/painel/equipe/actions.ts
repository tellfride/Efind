"use server";

// Ações da equipe. Toda ação: authorize(...) → validação zod → alvo carregado dentro da campanha e do
// escopo hierárquico do usuário → regras puras de src/server/team/rules.ts → gravação → auditoria.
import { revalidatePath } from "next/cache";
import { z } from "zod";
import { prisma, type Prisma } from "@/lib/db";
import { authorize } from "@/lib/auth";
import { audit } from "@/lib/audit";
import { actionError, actionOk, zodToActionError, type ActionResult } from "@/lib/action-result";
import { CAMPAIGN_ROLES } from "@/lib/constants";
import { appUrl } from "@/lib/env";
import { generateTempPassword, hashPassword, passwordSchema } from "@/lib/password";
import { normalizeBrPhone, whatsappLink } from "@/lib/phone";
import { registrationUrl } from "@/lib/qrcode";
import { teamScopeWhere } from "@/server/access";
import {
  countOtherActiveAdmins,
  findMemberInScope,
  hasActiveCoordinators,
  isUniqueViolation,
  loadCandidates,
  uniqueInviteCode,
} from "@/server/team/queries";
import {
  buildAccessMessage,
  canManageMember,
  checkSelfAndLastAdmin,
  isCampaignRole,
  resolvePlacement,
  validateDeletePlan,
  validateRoleChange,
} from "@/server/team/rules";
import type { CreatedMemberData, ResetPasswordData } from "@/components/team/types";

// ---------- Campos ----------

const idField = z.string().trim().min(1, "Identificador inválido").max(64, "Identificador inválido");
const nameField = z.string().trim().min(3, "Informe o nome completo").max(120, "Nome muito longo");
const emailField = z.string().trim().toLowerCase().email("Informe um e-mail válido").max(160, "E-mail muito longo");
const phoneField = z
  .string()
  .trim()
  .max(30, "Telefone inválido")
  .optional()
  .transform((v) => (v ? v : undefined))
  .refine((v) => !v || normalizeBrPhone(v) !== null, "Telefone inválido. Use DDD + número, ex.: (11) 98765-4321");
const goalField = z.preprocess(
  (v) => (v === undefined || v === null || (typeof v === "string" && v.trim() === "") ? null : Number(v)),
  z
    .number({ invalid_type_error: "Informe um número" })
    .int("Use um número inteiro")
    .min(0, "A meta não pode ser negativa")
    .max(1_000_000, "Meta muito alta")
    .nullable(),
);
const regionField = z
  .string()
  .trim()
  .max(120, "Máximo de 120 caracteres")
  .optional()
  .transform((v) => (v ? v : null));
const roleField = z.enum(CAMPAIGN_ROLES, { errorMap: () => ({ message: "Escolha um papel válido" }) }).optional();
const optionalId = z
  .string()
  .trim()
  .max(64)
  .optional()
  .transform((v) => (v ? v : undefined));

const EMAIL_TAKEN = "Este e-mail já está cadastrado no E-Find. Use outro e-mail.";

function fieldError(error: string, field: string | null): ActionResult<never> {
  return actionError(error, field ? { [field]: [error] } : undefined);
}

function revalidateMember(id: string) {
  revalidatePath("/painel/equipe");
  revalidatePath(`/painel/equipe/${id}`);
}

// ---------- Criar ----------

const createSchema = z.object({
  name: nameField,
  email: emailField,
  phone: phoneField,
  role: roleField,
  parentId: optionalId,
  goal: goalField,
  region: regionField,
  password: z
    .string()
    .optional()
    .transform((v) => (v ? v : undefined))
    .pipe(passwordSchema.optional()),
});

export async function createMemberAction(
  _prev: ActionResult<CreatedMemberData>,
  formData: FormData,
): Promise<ActionResult<CreatedMemberData>> {
  const auth = await authorize("equipe", "create");
  if (!auth.ok) return actionError(auth.error);
  const me = auth.user;
  if (me.role === "CABO") return actionError("Cabos eleitorais não podem cadastrar membros na equipe.");

  const parsed = createSchema.safeParse(Object.fromEntries(formData));
  if (!parsed.success) return zodToActionError(parsed.error);
  const d = parsed.data;

  // Coordenador: papel e superior são forçados no servidor (CABO abaixo dele), seja qual for a entrada
  const [coordinatorsActive, candidates] = await Promise.all([
    hasActiveCoordinators(me.campaignId),
    loadCandidates(me.campaignId, [d.parentId, me.id]),
  ]);
  const placement = resolvePlacement({
    actor: me,
    requestedRole: d.role,
    requestedParentId: d.parentId,
    candidates,
    hasActiveCoordinators: coordinatorsActive,
  });
  if (!placement.ok) return fieldError(placement.error, placement.field);

  const taken = await prisma.user.findUnique({ where: { email: d.email }, select: { id: true } });
  if (taken) return fieldError(EMAIL_TAKEN, "email");

  const password = d.password ?? generateTempPassword();
  const phone = d.phone ? normalizeBrPhone(d.phone) : null;

  let created: { id: string; name: string; email: string; inviteCode: string };
  try {
    created = await prisma.user.create({
      data: {
        campaignId: me.campaignId,
        name: d.name,
        email: d.email,
        phone,
        passwordHash: await hashPassword(password),
        role: placement.role,
        parentId: placement.parentId,
        inviteCode: await uniqueInviteCode(),
        goal: d.goal,
        region: d.region,
      },
      select: { id: true, name: true, email: true, inviteCode: true },
    });
  } catch (err) {
    if (isUniqueViolation(err, "email")) return fieldError(EMAIL_TAKEN, "email");
    if (isUniqueViolation(err)) return actionError("Não foi possível gerar o link de cadastro. Tente novamente.");
    throw err;
  }

  await audit({
    action: "user.create",
    campaignId: me.campaignId,
    userId: me.id,
    entity: "User",
    entityId: created.id,
    details: { role: placement.role, parentId: placement.parentId, goal: d.goal },
  });
  revalidatePath("/painel/equipe");

  const loginUrl = appUrl("/login");
  const regUrl = registrationUrl(created.inviteCode);
  const message = buildAccessMessage({
    memberName: created.name,
    campaignName: me.campaign.ballotName,
    role: placement.role,
    loginUrl,
    email: created.email,
    password,
    registrationUrl: regUrl,
  });
  return actionOk("Membro cadastrado.", {
    id: created.id,
    name: created.name,
    email: created.email,
    password,
    loginUrl,
    registrationUrl: regUrl,
    message,
    whatsappUrl: phone ? whatsappLink(phone, message) : null,
  });
}

// ---------- Editar ----------

const updateSchema = z.object({
  memberId: idField,
  name: nameField,
  phone: phoneField,
  goal: goalField,
  region: regionField,
  // Somente ADMIN (ignorados para coordenadores)
  email: emailField.optional(),
  role: roleField,
  parentId: optionalId,
});

export async function updateMemberAction(_prev: ActionResult, formData: FormData): Promise<ActionResult> {
  const auth = await authorize("equipe", "edit");
  if (!auth.ok) return actionError(auth.error);
  const me = auth.user;

  const parsed = updateSchema.safeParse(Object.fromEntries(formData));
  if (!parsed.success) return zodToActionError(parsed.error);
  const d = parsed.data;

  const target = await findMemberInScope(me, d.memberId);
  if (!target || !isCampaignRole(target.role)) return actionError("Membro não encontrado.");
  if (!canManageMember(me, target)) return actionError("Você não tem permissão para editar este membro.");

  const phone = d.phone ? normalizeBrPhone(d.phone) : null;
  const data: Prisma.UserUncheckedUpdateInput = { name: d.name, phone, goal: d.goal, region: d.region };
  const changed: string[] = [];
  if (d.name !== target.name) changed.push("name");
  if (phone !== target.phone) changed.push("phone");
  if (d.goal !== target.goal) changed.push("goal");
  if (d.region !== target.region) changed.push("region");

  let roleChanged = false;
  let newParentId = target.parentId;

  if (me.role === "ADMIN") {
    if (d.email && d.email !== target.email) {
      const taken = await prisma.user.findFirst({ where: { email: d.email, id: { not: target.id } }, select: { id: true } });
      if (taken) return fieldError(EMAIL_TAKEN, "email");
      data.email = d.email;
      changed.push("email");
    }

    const newRole = d.role ?? target.role;
    if (newRole !== target.role) {
      const [childrenCount, otherAdmins] = await Promise.all([
        prisma.user.count({ where: { campaignId: me.campaignId, parentId: target.id } }),
        countOtherActiveAdmins(me.campaignId, target.id),
      ]);
      const err = validateRoleChange({ actor: me, target, newRole, childrenCount, otherActiveAdmins: otherAdmins });
      if (err) return fieldError(err, "role");
    }

    const [coordinatorsActive, candidates] = await Promise.all([
      hasActiveCoordinators(me.campaignId, target.id),
      loadCandidates(me.campaignId, [d.parentId, me.id, target.parentId]),
    ]);
    const placement = resolvePlacement({
      actor: me,
      requestedRole: newRole,
      requestedParentId: d.parentId,
      candidates,
      hasActiveCoordinators: coordinatorsActive,
      target,
    });
    if (!placement.ok) return fieldError(placement.error, placement.field);
    data.role = placement.role;
    data.parentId = placement.parentId;
    newParentId = placement.parentId;
    roleChanged = placement.role !== target.role;
    if (roleChanged) changed.push("role");
    if (placement.parentId !== target.parentId) changed.push("parentId");
  }

  try {
    await prisma.$transaction(async (tx) => {
      await tx.user.update({ where: { id: target.id }, data });
      // Exceções de permissão valem para o papel anterior: são descartadas ao trocar o papel
      if (roleChanged) await tx.userPermission.deleteMany({ where: { userId: target.id } });
    });
  } catch (err) {
    if (isUniqueViolation(err, "email")) return fieldError(EMAIL_TAKEN, "email");
    throw err;
  }

  await audit({
    action: "user.update",
    campaignId: me.campaignId,
    userId: me.id,
    entity: "User",
    entityId: target.id,
    details: {
      fields: changed,
      ...(roleChanged ? { roleFrom: target.role, roleTo: data.role } : {}),
      ...(newParentId !== target.parentId ? { parentFrom: target.parentId, parentTo: newParentId } : {}),
    },
  });
  revalidateMember(target.id);
  return actionOk(changed.length ? "Dados atualizados." : "Nenhuma alteração para salvar.");
}

// ---------- Mover para outro responsável (ADMIN) ----------

const moveSchema = z.object({ memberId: idField, parentId: idField });

export async function moveMemberAction(_prev: ActionResult, formData: FormData): Promise<ActionResult> {
  const auth = await authorize("equipe", "edit");
  if (!auth.ok) return actionError(auth.error);
  const me = auth.user;
  if (me.role !== "ADMIN") return actionError("Apenas administradores podem mover membros entre coordenadores.");

  const parsed = moveSchema.safeParse(Object.fromEntries(formData));
  if (!parsed.success) return zodToActionError(parsed.error);
  const d = parsed.data;

  const target = await findMemberInScope(me, d.memberId);
  if (!target || !isCampaignRole(target.role)) return actionError("Membro não encontrado.");
  if (target.role === "ADMIN") return actionError("Administradores não ficam abaixo de outro membro.");

  const [coordinatorsActive, candidates] = await Promise.all([
    hasActiveCoordinators(me.campaignId, target.id),
    loadCandidates(me.campaignId, [d.parentId]),
  ]);
  const placement = resolvePlacement({
    actor: me,
    requestedRole: target.role,
    requestedParentId: d.parentId,
    candidates,
    hasActiveCoordinators: coordinatorsActive,
    target,
  });
  if (!placement.ok) return fieldError(placement.error, placement.field);
  if (placement.parentId === target.parentId) return actionOk("O membro já está com este responsável.");

  await prisma.user.update({ where: { id: target.id }, data: { parentId: placement.parentId } });
  await audit({
    action: "user.update",
    campaignId: me.campaignId,
    userId: me.id,
    entity: "User",
    entityId: target.id,
    details: { fields: ["parentId"], moved: true, parentFrom: target.parentId, parentTo: placement.parentId },
  });
  revalidateMember(target.id);
  return actionOk("Membro movido. Os eleitores cadastrados por ele passam a aparecer na rede do novo responsável.");
}

// ---------- Ativar / desativar ----------

export async function setMemberActiveAction(memberId: string, active: boolean): Promise<ActionResult> {
  const auth = await authorize("equipe", "edit");
  if (!auth.ok) return actionError(auth.error);
  const me = auth.user;

  const parsed = z.object({ memberId: idField, active: z.boolean() }).safeParse({ memberId, active });
  if (!parsed.success) return actionError("Dados inválidos.");

  const target = await findMemberInScope(me, parsed.data.memberId);
  if (!target) return actionError("Membro não encontrado.");
  if (!canManageMember(me, target)) return actionError("Você não tem permissão para alterar este membro.");

  if (!parsed.data.active) {
    const otherAdmins = target.role === "ADMIN" ? await countOtherActiveAdmins(me.campaignId, target.id) : 1;
    const err = checkSelfAndLastAdmin("deactivate", me.id, target, otherAdmins);
    if (err) return actionError(err);
  }
  if (target.active === parsed.data.active) {
    return actionOk(parsed.data.active ? "O membro já está ativo." : "O membro já está desativado.");
  }

  await prisma.user.update({
    where: { id: target.id },
    // Desativar encerra as sessões abertas (sessionVersion) — o link público também deixa de funcionar
    data: parsed.data.active ? { active: true } : { active: false, sessionVersion: { increment: 1 } },
  });
  await audit({
    action: parsed.data.active ? "user.activate" : "user.deactivate",
    campaignId: me.campaignId,
    userId: me.id,
    entity: "User",
    entityId: target.id,
    details: { role: target.role },
  });
  revalidateMember(target.id);
  return actionOk(parsed.data.active ? "Acesso reativado." : "Acesso desativado. As sessões abertas foram encerradas.");
}

// ---------- Redefinir senha ----------

export async function resetMemberPasswordAction(memberId: string): Promise<ActionResult<ResetPasswordData>> {
  const auth = await authorize("equipe", "edit");
  if (!auth.ok) return actionError(auth.error);
  const me = auth.user;

  const parsed = idField.safeParse(memberId);
  if (!parsed.success) return actionError("Dados inválidos.");

  const target = await findMemberInScope(me, parsed.data);
  if (!target || !isCampaignRole(target.role)) return actionError("Membro não encontrado.");
  if (!canManageMember(me, target)) return actionError("Você não tem permissão para alterar este membro.");
  const err = checkSelfAndLastAdmin("reset_password", me.id, target, 1);
  if (err) return actionError(err);

  const password = generateTempPassword();
  await prisma.user.update({
    where: { id: target.id },
    data: { passwordHash: await hashPassword(password), sessionVersion: { increment: 1 } },
  });
  await audit({
    action: "user.password_reset",
    campaignId: me.campaignId,
    userId: me.id,
    entity: "User",
    entityId: target.id,
  });

  const loginUrl = appUrl("/login");
  const message = buildAccessMessage({
    memberName: target.name,
    campaignName: me.campaign.ballotName,
    role: target.role,
    loginUrl,
    email: target.email,
    password,
    reset: true,
  });
  return actionOk("Senha redefinida. As sessões abertas foram encerradas.", {
    email: target.email,
    password,
    loginUrl,
    message,
    whatsappUrl: target.phone ? whatsappLink(target.phone, message) : null,
  });
}

// ---------- Novo link de cadastro ----------

export async function regenerateInviteAction(memberId: string): Promise<ActionResult> {
  const auth = await authorize("equipe", "edit");
  if (!auth.ok) return actionError(auth.error);
  const me = auth.user;

  const parsed = idField.safeParse(memberId);
  if (!parsed.success) return actionError("Dados inválidos.");

  const target = await findMemberInScope(me, parsed.data);
  if (!target) return actionError("Membro não encontrado.");
  if (target.id !== me.id && !canManageMember(me, target)) {
    return actionError("Você não tem permissão para alterar este membro.");
  }

  let code: string;
  try {
    code = await uniqueInviteCode();
    await prisma.user.update({ where: { id: target.id }, data: { inviteCode: code } });
  } catch (err) {
    if (isUniqueViolation(err)) return actionError("Não foi possível gerar um novo link. Tente novamente.");
    throw err;
  }
  await audit({
    action: "user.update",
    campaignId: me.campaignId,
    userId: me.id,
    entity: "User",
    entityId: target.id,
    details: { fields: ["inviteCode"], registrationLinkRegenerated: true },
  });
  revalidateMember(target.id);
  revalidatePath("/painel/meu-link");
  return actionOk("Novo link gerado. O link e o QR Code anteriores deixaram de funcionar.");
}

// ---------- Excluir ----------

const deleteSchema = z.object({ memberId: idField, transferToId: optionalId, newParentId: optionalId });

class DeleteConflictError extends Error {}

export async function deleteMemberAction(_prev: ActionResult, formData: FormData): Promise<ActionResult> {
  const auth = await authorize("equipe", "delete");
  if (!auth.ok) return actionError(auth.error);
  const me = auth.user;

  const parsed = deleteSchema.safeParse(Object.fromEntries(formData));
  if (!parsed.success) return zodToActionError(parsed.error);
  const d = parsed.data;

  const target = await findMemberInScope(me, d.memberId);
  if (!target) return actionError("Membro não encontrado.");
  if (!canManageMember(me, target)) return actionError("Você não tem permissão para excluir este membro.");

  const otherAdmins = target.role === "ADMIN" ? await countOtherActiveAdmins(me.campaignId, target.id) : 1;
  const guard = checkSelfAndLastAdmin("delete", me.id, target, otherAdmins);
  if (guard) return actionError(guard);

  const [votersCount, childrenCount, otherCoordinators] = await Promise.all([
    prisma.voter.count({ where: { campaignId: me.campaignId, registeredById: target.id } }),
    prisma.user.count({ where: { campaignId: me.campaignId, parentId: target.id } }),
    hasActiveCoordinators(me.campaignId, target.id),
  ]);

  // Quem recebe os eleitores precisa estar no escopo de quem exclui; o novo responsável, na campanha
  const [transferTo, newParent] = await Promise.all([
    votersCount > 0 && d.transferToId
      ? prisma.user.findFirst({
          where: { AND: [teamScopeWhere(me), { id: d.transferToId }] },
          select: { id: true, role: true, active: true },
        })
      : Promise.resolve(null),
    childrenCount > 0 && d.newParentId
      ? prisma.user.findFirst({
          where: { campaignId: me.campaignId, id: d.newParentId },
          select: { id: true, role: true, active: true },
        })
      : Promise.resolve(null),
  ]);

  const plan = validateDeletePlan({
    target,
    votersCount,
    childrenCount,
    transferTo,
    newParent,
    hasOtherActiveCoordinators: otherCoordinators,
  });
  if (!plan.ok) return fieldError(plan.error, plan.field);

  let votersTransferred = 0;
  let childrenMoved = 0;
  try {
    await prisma.$transaction(async (tx) => {
      if (transferTo) {
        const res = await tx.voter.updateMany({
          where: { campaignId: me.campaignId, registeredById: target.id },
          data: { registeredById: transferTo.id },
        });
        votersTransferred = res.count;
      }
      if (await tx.voter.count({ where: { registeredById: target.id } })) {
        throw new DeleteConflictError("Este membro cadastrou eleitores agora há pouco. Escolha para quem transferi-los e tente novamente.");
      }
      if (newParent) {
        const res = await tx.user.updateMany({
          where: { campaignId: me.campaignId, parentId: target.id },
          data: { parentId: newParent.id },
        });
        childrenMoved = res.count;
      }
      if (await tx.user.count({ where: { parentId: target.id } })) {
        throw new DeleteConflictError("Há membros vinculados a este usuário. Escolha o novo responsável e tente novamente.");
      }
      await tx.user.delete({ where: { id: target.id } });
    });
  } catch (err) {
    if (err instanceof DeleteConflictError) return actionError(err.message);
    throw err;
  }

  await audit({
    action: "user.delete",
    campaignId: me.campaignId,
    userId: me.id,
    entity: "User",
    entityId: target.id,
    details: {
      name: target.name,
      role: target.role,
      votersTransferred,
      transferToId: transferTo?.id ?? null,
      childrenMoved,
      newParentId: newParent?.id ?? null,
    },
  });
  // Sem revalidatePath aqui: a página atual (do membro excluído) não deve ser renderizada de novo;
  // o cliente navega para /painel/equipe, que é dinâmica e busca dados novos.
  return actionOk(
    votersTransferred
      ? `Membro excluído. ${votersTransferred} eleitor(es) transferido(s).`
      : "Membro excluído.",
  );
}
