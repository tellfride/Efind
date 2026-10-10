"use server";

// Ações dos modelos de mensagem. Modelos pertencem à campanha (sem escopo hierárquico).
import { revalidatePath } from "next/cache";
import { z } from "zod";
import { prisma } from "@/lib/db";
import { authorize } from "@/lib/auth";
import { audit } from "@/lib/audit";
import { actionError, actionOk, zodToActionError, type ActionResult } from "@/lib/action-result";
import { BROADCAST_STATUS_LABELS } from "@/lib/constants";
import { TEMPLATE_LOCKING_STATUSES, parseProviderVariables } from "@/server/messaging/logic";
import { parseVariablesField, templateInputSchema } from "@/server/messaging/template-schema";

const idSchema = z.string().trim().min(1).max(64);
const LIST_PATH = "/painel/mensagens/modelos";

function readTemplateForm(formData: FormData) {
  const text = (key: string) => {
    const v = formData.get(key);
    return typeof v === "string" ? v : undefined;
  };
  return {
    name: text("name") ?? "",
    category: text("category"),
    type: text("type"),
    body: text("body") ?? "",
    mediaUrl: text("mediaUrl"),
    providerTemplateName: text("providerTemplateName"),
    providerTemplateLanguage: text("providerTemplateLanguage"),
    providerVariables: parseVariablesField(formData.get("providerVariables")),
  };
}

/** Cria (sem id) ou atualiza (com id) um modelo */
export async function saveTemplateAction(
  _prev: ActionResult<{ id: string }>,
  formData: FormData,
): Promise<ActionResult<{ id: string }>> {
  const rawId = formData.get("id");
  const id = typeof rawId === "string" && rawId ? rawId : null;
  const auth = await authorize("modelos", id ? "edit" : "create");
  if (!auth.ok) return actionError(auth.error);
  const user = auth.user;

  const parsed = templateInputSchema.safeParse(readTemplateForm(formData));
  if (!parsed.success) return zodToActionError(parsed.error);
  const d = parsed.data;
  const data = {
    name: d.name,
    category: d.category,
    type: d.type,
    body: d.body,
    mediaUrl: d.mediaUrl,
    providerTemplateName: d.providerTemplateName,
    providerTemplateLanguage: d.providerTemplateLanguage,
    providerVariables: d.providerVariables,
  };

  if (id) {
    if (!idSchema.safeParse(id).success) return actionError("Modelo não encontrado.");
    const existing = await prisma.messageTemplate.findFirst({
      where: { id, campaignId: user.campaignId },
      select: { id: true },
    });
    if (!existing) return actionError("Modelo não encontrado.");
    await prisma.messageTemplate.update({ where: { id: existing.id }, data });
    await audit({
      action: "template.update",
      campaignId: user.campaignId,
      userId: user.id,
      entity: "MessageTemplate",
      entityId: existing.id,
      details: { name: d.name, category: d.category, type: d.type, approvedTemplate: !!d.providerTemplateName },
    });
    revalidatePath(LIST_PATH);
    revalidatePath(`${LIST_PATH}/${existing.id}`);
    return actionOk("Modelo atualizado.", { id: existing.id });
  }

  const created = await prisma.messageTemplate.create({
    data: { ...data, campaignId: user.campaignId, createdById: user.id },
    select: { id: true },
  });
  await audit({
    action: "template.create",
    campaignId: user.campaignId,
    userId: user.id,
    entity: "MessageTemplate",
    entityId: created.id,
    details: { name: d.name, category: d.category, type: d.type, approvedTemplate: !!d.providerTemplateName },
  });
  revalidatePath(LIST_PATH);
  return actionOk("Modelo criado.", { id: created.id });
}

/** Cria uma cópia do modelo (para variações de texto) */
export async function duplicateTemplateAction(templateId: string): Promise<ActionResult<{ id: string }>> {
  const auth = await authorize("modelos", "create");
  if (!auth.ok) return actionError(auth.error);
  const user = auth.user;
  const parsedId = idSchema.safeParse(templateId);
  if (!parsedId.success) return actionError("Modelo não encontrado.");

  const source = await prisma.messageTemplate.findFirst({ where: { id: parsedId.data, campaignId: user.campaignId } });
  if (!source) return actionError("Modelo não encontrado.");

  const copy = await prisma.messageTemplate.create({
    data: {
      campaignId: user.campaignId,
      createdById: user.id,
      name: `Cópia de ${source.name}`.slice(0, 120),
      category: source.category,
      type: source.type,
      body: source.body,
      mediaUrl: source.mediaUrl,
      providerTemplateName: source.providerTemplateName,
      providerTemplateLanguage: source.providerTemplateLanguage,
      providerVariables: parseProviderVariables(source.providerVariables),
    },
    select: { id: true },
  });
  await audit({
    action: "template.create",
    campaignId: user.campaignId,
    userId: user.id,
    entity: "MessageTemplate",
    entityId: copy.id,
    details: { duplicatedFrom: source.id, name: source.name },
  });
  revalidatePath(LIST_PATH);
  return actionOk("Modelo duplicado. Ajuste a cópia e salve.", { id: copy.id });
}

/** Exclui um modelo que não esteja em uso por disparos agendados, em andamento ou pausados */
export async function deleteTemplateAction(templateId: string): Promise<ActionResult> {
  const auth = await authorize("modelos", "delete");
  if (!auth.ok) return actionError(auth.error);
  const user = auth.user;
  const parsedId = idSchema.safeParse(templateId);
  if (!parsedId.success) return actionError("Modelo não encontrado.");

  const template = await prisma.messageTemplate.findFirst({
    where: { id: parsedId.data, campaignId: user.campaignId },
    select: { id: true, name: true },
  });
  if (!template) return actionError("Modelo não encontrado.");

  const inUse = await prisma.broadcast.findFirst({
    where: { campaignId: user.campaignId, templateId: template.id, status: { in: TEMPLATE_LOCKING_STATUSES } },
    select: { name: true, status: true },
  });
  if (inUse) {
    const label = BROADCAST_STATUS_LABELS[inUse.status as keyof typeof BROADCAST_STATUS_LABELS] ?? inUse.status;
    return actionError(
      `Este modelo está em uso pelo disparo “${inUse.name}” (${label.toLowerCase()}). Conclua ou cancele o disparo antes de excluir.`,
    );
  }

  await prisma.messageTemplate.delete({ where: { id: template.id } });
  await audit({
    action: "template.delete",
    campaignId: user.campaignId,
    userId: user.id,
    entity: "MessageTemplate",
    entityId: template.id,
    details: { name: template.name },
  });
  revalidatePath(LIST_PATH);
  return actionOk("Modelo excluído.");
}
