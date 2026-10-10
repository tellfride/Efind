"use server";

// Ações do super admin sobre campanhas (tenants) e seus administradores.
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";
import { prisma } from "@/lib/db";
import { authorizeSuperAdmin } from "@/lib/auth";
import { audit } from "@/lib/audit";
import { appUrl } from "@/lib/env";
import { generateTempPassword, hashPassword } from "@/lib/password";
import { actionError, actionOk, formDataToObject, zodToActionError, type ActionResult } from "@/lib/action-result";
import type { CampaignStatus } from "@/lib/constants";
import { bootstrapCampaign } from "@/server/campaign/bootstrap";
import { emailInUse, isUniqueViolation, safeErrorTag, uniqueInviteCode } from "./accounts";
import { campaignSlugBase, uniqueSlug } from "./slug";
import {
  accountFormSchema,
  campaignFormSchema,
  campaignStatusSchema,
  changedFields,
  deleteCampaignSchema,
  idSchema,
  parseCreateCampaignInput,
  type CreatedCampaign,
  type IssuedCredentials,
} from "./validation";

const EMAIL_TAKEN = "Este e-mail já está cadastrado no E-Find. Use outro.";

function revalidateCampaign(campaignId?: string) {
  revalidatePath("/super", "layout");
  if (campaignId) revalidatePath(`/super/campanhas/${campaignId}`);
}

// ---------- Criação ----------

export async function createCampaignAction(
  _prev: ActionResult<CreatedCampaign>,
  formData: FormData,
): Promise<ActionResult<CreatedCampaign>> {
  const auth = await authorizeSuperAdmin();
  if (!auth.ok) return actionError(auth.error);

  const parsed = parseCreateCampaignInput(formDataToObject(formData));
  if (!parsed.success) return actionError("Verifique os campos destacados.", parsed.fieldErrors);
  const { campaign: data, admin } = parsed.data;

  if (await emailInUse(admin.email)) return actionError(EMAIL_TAKEN, { adminEmail: [EMAIL_TAKEN] });

  const password = admin.password ?? generateTempPassword();
  const passwordHash = await hashPassword(password);
  const base = campaignSlugBase(data.ballotName);

  let created: { campaignId: string; slug: string; adminId: string } | null = null;
  for (let attempt = 0; attempt < 3 && !created; attempt++) {
    try {
      created = await prisma.$transaction(
        async (tx) => {
          const existing = await tx.campaign.findMany({ where: { slug: { startsWith: base } }, select: { slug: true } });
          const slug = uniqueSlug(
            base,
            existing.map((c) => c.slug),
          );
          const campaign = await tx.campaign.create({ data: { ...data, slug } });
          await bootstrapCampaign(tx, campaign.id);
          const user = await tx.user.create({
            data: {
              campaignId: campaign.id,
              name: admin.name,
              email: admin.email,
              phone: admin.phone,
              passwordHash,
              role: "ADMIN",
              inviteCode: await uniqueInviteCode(tx),
            },
            select: { id: true },
          });
          return { campaignId: campaign.id, slug, adminId: user.id };
        },
        { timeout: 30_000 },
      );
    } catch (err) {
      if (isUniqueViolation(err, "email")) return actionError(EMAIL_TAKEN, { adminEmail: [EMAIL_TAKEN] });
      // Corrida com outra criação simultânea: tenta de novo com slug/código recalculados
      if (isUniqueViolation(err, "slug") || isUniqueViolation(err, "inviteCode")) continue;
      console.error("[super] falha ao criar campanha:", safeErrorTag(err));
      return actionError("Não foi possível criar a campanha. Tente novamente.");
    }
  }
  if (!created) return actionError("Não foi possível criar a campanha. Tente novamente.");

  await audit({
    action: "campaign.create",
    campaignId: created.campaignId,
    userId: auth.user.id,
    entity: "Campaign",
    entityId: created.campaignId,
    details: { slug: created.slug, ballotName: data.ballotName, office: data.office },
  });
  await audit({
    action: "user.create",
    campaignId: created.campaignId,
    userId: auth.user.id,
    entity: "User",
    entityId: created.adminId,
    details: { role: "ADMIN", email: admin.email, passwordGenerated: !admin.password },
  });
  revalidateCampaign();

  return actionOk("Campanha criada com sucesso.", {
    campaignId: created.campaignId,
    ballotName: data.ballotName,
    credentials: {
      name: admin.name,
      email: admin.email,
      password,
      generated: !admin.password,
      loginUrl: appUrl("/login"),
    },
  });
}

// ---------- Edição ----------

export async function updateCampaignAction(_prev: ActionResult, formData: FormData): Promise<ActionResult> {
  const auth = await authorizeSuperAdmin();
  if (!auth.ok) return actionError(auth.error);

  const raw = formDataToObject(formData);
  const id = idSchema.safeParse(raw.campaignId);
  if (!id.success) return actionError("Campanha inválida.");
  const parsed = campaignFormSchema.safeParse(raw);
  if (!parsed.success) return zodToActionError(parsed.error);

  const current = await prisma.campaign.findUnique({
    where: { id: id.data },
    select: {
      candidateName: true,
      ballotName: true,
      ballotNumber: true,
      party: true,
      office: true,
      city: true,
      state: true,
      electionYear: true,
      primaryColor: true,
      voterGoal: true,
    },
  });
  if (!current) return actionError("Campanha não encontrada.");

  const changed = changedFields(current, parsed.data);
  if (!changed.length) return actionOk("Nenhuma alteração para salvar.");

  await prisma.campaign.update({ where: { id: id.data }, data: parsed.data });
  await audit({
    action: "campaign.update",
    campaignId: id.data,
    userId: auth.user.id,
    entity: "Campaign",
    entityId: id.data,
    details: { fields: changed },
  });
  revalidateCampaign(id.data);
  revalidatePath("/painel", "layout");
  return actionOk("Dados da campanha atualizados.");
}

// ---------- Suspender / reativar ----------

export async function setCampaignStatusAction(input: { campaignId: string; status: CampaignStatus }): Promise<ActionResult> {
  const auth = await authorizeSuperAdmin();
  if (!auth.ok) return actionError(auth.error);
  const parsed = campaignStatusSchema.safeParse(input);
  if (!parsed.success) return actionError("Dados inválidos.");
  const { campaignId, status } = parsed.data;

  const campaign = await prisma.campaign.findUnique({ where: { id: campaignId }, select: { status: true, slug: true } });
  if (!campaign) return actionError("Campanha não encontrada.");
  if (campaign.status === status) {
    return actionOk(status === "ACTIVE" ? "A campanha já está ativa." : "A campanha já está suspensa.");
  }

  const pausedBroadcasts = await prisma.$transaction(async (tx) => {
    await tx.campaign.update({ where: { id: campaignId }, data: { status } });
    if (status !== "SUSPENDED") return 0;
    // Campanha suspensa não pode continuar enviando mensagens
    const res = await tx.broadcast.updateMany({ where: { campaignId, status: "RUNNING" }, data: { status: "PAUSED" } });
    return res.count;
  });

  await audit({
    action: status === "SUSPENDED" ? "campaign.suspend" : "campaign.activate",
    campaignId,
    userId: auth.user.id,
    entity: "Campaign",
    entityId: campaignId,
    details: status === "SUSPENDED" ? { slug: campaign.slug, pausedBroadcasts } : { slug: campaign.slug },
  });
  revalidateCampaign(campaignId);

  if (status === "ACTIVE") return actionOk("Campanha reativada. A equipe já pode entrar novamente.");
  return actionOk(
    pausedBroadcasts > 0
      ? `Campanha suspensa. ${pausedBroadcasts} disparo(s) em andamento foram pausados.`
      : "Campanha suspensa. Ninguém da equipe consegue entrar até a reativação.",
  );
}

// ---------- Exclusão definitiva ----------

export async function deleteCampaignAction(_prev: ActionResult, formData: FormData): Promise<ActionResult> {
  const auth = await authorizeSuperAdmin();
  if (!auth.ok) return actionError(auth.error);
  const parsed = deleteCampaignSchema.safeParse(formDataToObject(formData));
  if (!parsed.success) return zodToActionError(parsed.error);
  const { campaignId, confirmSlug } = parsed.data;

  const campaign = await prisma.campaign.findUnique({ where: { id: campaignId }, select: { id: true, slug: true, ballotName: true } });
  if (!campaign) return actionError("Campanha não encontrada.");
  if (confirmSlug !== campaign.slug) {
    return actionError("O identificador digitado não confere.", { confirmSlug: ["Digite exatamente o identificador indicado"] });
  }

  try {
    await prisma.$transaction(
      async (tx) => {
        // Voter.registeredBy é Restrict: eleitores saem antes dos usuários (que caem em cascata com a campanha)
        await tx.voter.deleteMany({ where: { campaignId } });
        await tx.campaign.delete({ where: { id: campaignId } });
      },
      { timeout: 120_000 },
    );
  } catch (err) {
    console.error("[super] falha ao excluir campanha:", safeErrorTag(err));
    return actionError("Não foi possível excluir a campanha agora. Tente novamente em instantes.");
  }

  await audit({
    action: "campaign.delete",
    campaignId: null,
    userId: auth.user.id,
    entity: "Campaign",
    entityId: campaignId,
    details: { slug: campaign.slug, ballotName: campaign.ballotName },
  });
  revalidateCampaign();
  redirect("/super/campanhas?excluida=1");
}

// ---------- Administradores da campanha ----------

export async function createCampaignAdminAction(
  _prev: ActionResult<IssuedCredentials>,
  formData: FormData,
): Promise<ActionResult<IssuedCredentials>> {
  const auth = await authorizeSuperAdmin();
  if (!auth.ok) return actionError(auth.error);

  const raw = formDataToObject(formData);
  const campaignId = idSchema.safeParse(raw.campaignId);
  if (!campaignId.success) return actionError("Campanha inválida.");
  const parsed = accountFormSchema.safeParse(raw);
  if (!parsed.success) return zodToActionError(parsed.error);
  const data = parsed.data;

  const campaign = await prisma.campaign.findUnique({ where: { id: campaignId.data }, select: { id: true } });
  if (!campaign) return actionError("Campanha não encontrada.");
  if (await emailInUse(data.email)) return actionError(EMAIL_TAKEN, { email: [EMAIL_TAKEN] });

  const password = data.password ?? generateTempPassword();
  let userId: string;
  try {
    const user = await prisma.user.create({
      data: {
        campaignId: campaign.id,
        name: data.name,
        email: data.email,
        phone: data.phone,
        passwordHash: await hashPassword(password),
        role: "ADMIN",
        inviteCode: await uniqueInviteCode(prisma),
      },
      select: { id: true },
    });
    userId = user.id;
  } catch (err) {
    if (isUniqueViolation(err, "email")) return actionError(EMAIL_TAKEN, { email: [EMAIL_TAKEN] });
    console.error("[super] falha ao criar administrador:", safeErrorTag(err));
    return actionError("Não foi possível criar o administrador. Tente novamente.");
  }

  await audit({
    action: "user.create",
    campaignId: campaign.id,
    userId: auth.user.id,
    entity: "User",
    entityId: userId,
    details: { role: "ADMIN", email: data.email, passwordGenerated: !data.password },
  });
  revalidateCampaign(campaign.id);
  return actionOk("Administrador criado.", {
    name: data.name,
    email: data.email,
    password,
    generated: !data.password,
    loginUrl: appUrl("/login"),
  });
}

const adminTargetSchema = z.object({ campaignId: idSchema, userId: idSchema });

export async function resetCampaignAdminPasswordAction(input: {
  campaignId: string;
  userId: string;
}): Promise<ActionResult<IssuedCredentials>> {
  const auth = await authorizeSuperAdmin();
  if (!auth.ok) return actionError(auth.error);
  const parsed = adminTargetSchema.safeParse(input);
  if (!parsed.success) return actionError("Dados inválidos.");
  const { campaignId, userId } = parsed.data;

  const user = await prisma.user.findFirst({
    where: { id: userId, campaignId, role: "ADMIN" },
    select: { id: true, name: true, email: true },
  });
  if (!user) return actionError("Administrador não encontrado nesta campanha.");

  const password = generateTempPassword();
  await prisma.user.update({
    where: { id: user.id },
    data: { passwordHash: await hashPassword(password), sessionVersion: { increment: 1 } },
  });
  await audit({
    action: "user.password_reset",
    campaignId,
    userId: auth.user.id,
    entity: "User",
    entityId: user.id,
    details: { role: "ADMIN" },
  });
  revalidateCampaign(campaignId);
  return actionOk("Senha redefinida. As sessões abertas desse usuário foram encerradas.", {
    name: user.name,
    email: user.email,
    password,
    generated: true,
    loginUrl: appUrl("/login"),
  });
}

export async function setCampaignAdminActiveAction(input: {
  campaignId: string;
  userId: string;
  active: boolean;
}): Promise<ActionResult> {
  const auth = await authorizeSuperAdmin();
  if (!auth.ok) return actionError(auth.error);
  const parsed = adminTargetSchema.extend({ active: z.boolean() }).safeParse(input);
  if (!parsed.success) return actionError("Dados inválidos.");
  const { campaignId, userId, active } = parsed.data;

  const user = await prisma.user.findFirst({
    where: { id: userId, campaignId, role: "ADMIN" },
    select: { id: true, active: true },
  });
  if (!user) return actionError("Administrador não encontrado nesta campanha.");
  if (user.active === active) return actionOk(active ? "O administrador já está ativo." : "O administrador já está desativado.");

  if (!active) {
    const others = await prisma.user.count({ where: { campaignId, role: "ADMIN", active: true, id: { not: user.id } } });
    if (others === 0) {
      return actionError(
        "A campanha precisa de pelo menos um administrador ativo. Para bloquear o acesso de toda a equipe, suspenda a campanha.",
      );
    }
  }

  await prisma.user.update({
    where: { id: user.id },
    data: active ? { active: true } : { active: false, sessionVersion: { increment: 1 } },
  });
  await audit({
    action: active ? "user.activate" : "user.deactivate",
    campaignId,
    userId: auth.user.id,
    entity: "User",
    entityId: user.id,
    details: { role: "ADMIN" },
  });
  revalidateCampaign(campaignId);
  return actionOk(active ? "Administrador reativado." : "Administrador desativado. As sessões dele foram encerradas.");
}
