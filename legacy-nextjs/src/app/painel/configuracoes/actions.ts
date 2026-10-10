"use server";

// Ações da tela de configurações da campanha. Exigem configuracoes.edit e atuam SEMPRE na campanha
// do usuário logado (o id da campanha nunca vem do cliente).
import { revalidatePath } from "next/cache";
import { prisma } from "@/lib/db";
import { authorize } from "@/lib/auth";
import { audit } from "@/lib/audit";
import { actionError, actionOk, type ActionResult } from "@/lib/action-result";
import { parseFormConfig } from "@/lib/constants";
import {
  changedFields,
  flattenIssues,
  identityInputFromFormData,
  identitySchema,
  publicFormInputFromFormData,
  publicFormSchema,
} from "@/server/settings/schemas";

function validationError(fieldErrors: Record<string, string[]>): ActionResult {
  const first = fieldErrors._form?.[0];
  return actionError(first ?? "Verifique os campos destacados.", fieldErrors);
}

function revalidateCampaignPages() {
  revalidatePath("/painel", "layout");
  revalidatePath("/c/[code]", "page");
}

export async function updateIdentityAction(_prev: ActionResult, formData: FormData): Promise<ActionResult> {
  const auth = await authorize("configuracoes", "edit");
  if (!auth.ok) return actionError(auth.error);
  const { user } = auth;

  const parsed = identitySchema.safeParse(identityInputFromFormData(formData));
  if (!parsed.success) return validationError(flattenIssues(parsed.error));
  const d = parsed.data;

  const current = await prisma.campaign.findUnique({ where: { id: user.campaignId } });
  if (!current) return actionError("Campanha não encontrada.");

  const next = {
    candidateName: d.candidateName,
    ballotName: d.ballotName,
    ballotNumber: d.ballotNumber,
    party: d.party,
    office: d.office,
    city: d.city,
    state: d.state,
    electionYear: d.electionYear,
    voterGoal: d.voterGoal,
    primaryColor: d.primaryColor,
    logoUrl: d.logoAction === "replace" ? d.logoDataUrl! : d.logoAction === "remove" ? null : current.logoUrl,
  };
  const fields = changedFields(current, next);
  if (!fields.length) return actionOk("Nenhuma alteração para salvar.");

  await prisma.campaign.update({ where: { id: user.campaignId }, data: next });
  await audit({
    action: "settings.update",
    campaignId: user.campaignId,
    userId: user.id,
    entity: "Campaign",
    entityId: user.campaignId,
    details: { section: "identidade", fields },
  });
  revalidateCampaignPages();
  return actionOk("Identidade da campanha salva.");
}

export async function updatePublicFormAction(_prev: ActionResult, formData: FormData): Promise<ActionResult> {
  const auth = await authorize("configuracoes", "edit");
  if (!auth.ok) return actionError(auth.error);
  const { user } = auth;

  const parsed = publicFormSchema.safeParse(publicFormInputFromFormData(formData));
  if (!parsed.success) return validationError(flattenIssues(parsed.error));
  const d = parsed.data;

  const current = await prisma.campaign.findUnique({ where: { id: user.campaignId } });
  if (!current) return actionError("Campanha não encontrada.");

  const next = {
    formTitle: d.formTitle,
    formMessage: d.formMessage,
    formConfig: d.formConfig,
    consentText: d.consentText,
    privacyContact: d.privacyContact,
  };
  const fields = changedFields({ ...current, formConfig: parseFormConfig(current.formConfig) }, next);
  if (!fields.length) return actionOk("Nenhuma alteração para salvar.");

  await prisma.campaign.update({ where: { id: user.campaignId }, data: next });
  await audit({
    action: "settings.update",
    campaignId: user.campaignId,
    userId: user.id,
    entity: "Campaign",
    entityId: user.campaignId,
    details: { section: "formulario_publico", fields },
  });
  revalidateCampaignPages();
  return actionOk("Formulário público salvo.");
}
