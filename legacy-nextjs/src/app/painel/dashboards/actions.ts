"use server";

// Ações dos dashboards personalizáveis. Toda ação começa com authorize() e valida a entrada com zod;
// o dashboard alvo é sempre buscado pela campanha do usuário logado (nunca por id de campanha do cliente).
import { revalidatePath } from "next/cache";
import { z } from "zod";
import { prisma, type Prisma } from "@/lib/db";
import { authorize } from "@/lib/auth";
import { audit } from "@/lib/audit";
import { can } from "@/lib/permissions";
import { actionError, actionOk, zodToActionError, type ActionResult } from "@/lib/action-result";
import { dashboardWidgetsSchema } from "@/lib/dashboard-types";
import {
  createDefaultDashboards,
  isDashboardPresetKey,
  presetWidgets,
} from "@/server/dashboard/presets";
import {
  canDeleteDashboard,
  canDuplicateDashboard,
  canEditDashboard,
  canSetMyDefault,
  isDashboardVisible,
  resolveSharing,
} from "@/server/dashboard/rules";

/** Limite de dashboards próprios por usuário */
const MAX_OWN_DASHBOARDS = 50;

const idSchema = z.string().trim().min(1).max(64);

const nameSchema = z
  .string({ required_error: "Informe o nome do dashboard" })
  .trim()
  .min(2, "O nome deve ter pelo menos 2 caracteres")
  .max(80, "O nome pode ter no máximo 80 caracteres");
const descriptionSchema = z
  .string()
  .trim()
  .max(300, "A descrição pode ter no máximo 300 caracteres")
  .optional()
  .nullable()
  .transform((v) => (v ? v : null));

function revalidateDashboards(id?: string) {
  revalidatePath("/painel");
  revalidatePath("/painel/dashboards");
  if (id) {
    revalidatePath(`/painel/dashboards/${id}`);
    revalidatePath(`/painel/dashboards/${id}/editar`);
  }
}

async function findInCampaign(campaignId: string, id: string) {
  return prisma.dashboard.findFirst({ where: { id, campaignId } });
}

async function ensureOwnLimit(campaignId: string, userId: string): Promise<string | null> {
  const own = await prisma.dashboard.count({ where: { campaignId, ownerId: userId } });
  return own >= MAX_OWN_DASHBOARDS
    ? `Você já tem ${MAX_OWN_DASHBOARDS} dashboards. Exclua algum antes de criar outro.`
    : null;
}

// ---------- Criar ----------

const createSchema = z.object({
  name: nameSchema,
  description: descriptionSchema,
  preset: z
    .string()
    .refine((v) => v === "blank" || isDashboardPresetKey(v), "Escolha um ponto de partida")
    .default("blank"),
});

export async function createDashboardAction(
  _prev: ActionResult<{ id: string; canEdit: boolean }>,
  formData: FormData,
): Promise<ActionResult<{ id: string; canEdit: boolean }>> {
  const auth = await authorize("dashboard", "create");
  if (!auth.ok) return actionError(auth.error);
  const user = auth.user;

  const parsed = createSchema.safeParse({
    name: formData.get("name") ?? "",
    description: formData.get("description") ?? "",
    preset: formData.get("preset") ?? "blank",
  });
  if (!parsed.success) return zodToActionError(parsed.error);
  const limitError = await ensureOwnLimit(user.campaignId, user.id);
  if (limitError) return actionError(limitError);

  const { name, description, preset } = parsed.data;
  const widgets = isDashboardPresetKey(preset) ? presetWidgets(preset) : [];
  const created = await prisma.dashboard.create({
    data: {
      campaignId: user.campaignId,
      ownerId: user.id,
      name,
      description,
      shared: false,
      isDefault: false,
      widgets: widgets as unknown as Prisma.InputJsonValue,
    },
    select: { id: true },
  });
  await audit({
    action: "dashboard.create",
    campaignId: user.campaignId,
    userId: user.id,
    entity: "Dashboard",
    entityId: created.id,
    details: { name, preset, widgets: widgets.length },
  });
  revalidateDashboards();
  return actionOk("Dashboard criado.", { id: created.id, canEdit: can(user.permissions, "dashboard", "edit") });
}

// ---------- Duplicar ----------

export async function duplicateDashboardAction(id: string): Promise<ActionResult<{ id: string }>> {
  const auth = await authorize("dashboard", "create");
  if (!auth.ok) return actionError(auth.error);
  const user = auth.user;
  const parsedId = idSchema.safeParse(id);
  if (!parsedId.success) return actionError("Dashboard inválido.");

  const source = await findInCampaign(user.campaignId, parsedId.data);
  if (!source || !canDuplicateDashboard(user, source)) return actionError("Dashboard não encontrado.");
  const limitError = await ensureOwnLimit(user.campaignId, user.id);
  if (limitError) return actionError(limitError);

  const widgets = dashboardWidgetsSchema.safeParse(source.widgets);
  const name = `Cópia de ${source.name}`.slice(0, 80);
  const created = await prisma.dashboard.create({
    data: {
      campaignId: user.campaignId,
      ownerId: user.id,
      name,
      description: source.description,
      shared: false,
      isDefault: false,
      widgets: (widgets.success ? widgets.data : []) as unknown as Prisma.InputJsonValue,
    },
    select: { id: true },
  });
  await audit({
    action: "dashboard.create",
    campaignId: user.campaignId,
    userId: user.id,
    entity: "Dashboard",
    entityId: created.id,
    details: { name, duplicatedFrom: source.id },
  });
  revalidateDashboards();
  return actionOk("Dashboard duplicado.", { id: created.id });
}

// ---------- Excluir ----------

export async function deleteDashboardAction(id: string): Promise<ActionResult> {
  const auth = await authorize("dashboard", "view");
  if (!auth.ok) return actionError(auth.error);
  const user = auth.user;
  const parsedId = idSchema.safeParse(id);
  if (!parsedId.success) return actionError("Dashboard inválido.");

  const target = await findInCampaign(user.campaignId, parsedId.data);
  if (!target || !isDashboardVisible(user, target)) return actionError("Dashboard não encontrado.");
  if (!canDeleteDashboard(user, target)) return actionError("Você não tem permissão para excluir este dashboard.");

  await prisma.dashboard.delete({ where: { id: target.id } });
  await audit({
    action: "dashboard.delete",
    campaignId: user.campaignId,
    userId: user.id,
    entity: "Dashboard",
    entityId: target.id,
    details: { name: target.name, shared: target.shared, isDefault: target.isDefault },
  });
  revalidateDashboards(target.id);
  return actionOk("Dashboard excluído.");
}

// ---------- Meu padrão ----------

export async function toggleMyDefaultDashboardAction(id: string): Promise<ActionResult<{ isDefault: boolean }>> {
  const auth = await authorize("dashboard", "view");
  if (!auth.ok) return actionError(auth.error);
  const user = auth.user;
  const parsedId = idSchema.safeParse(id);
  if (!parsedId.success) return actionError("Dashboard inválido.");

  const target = await findInCampaign(user.campaignId, parsedId.data);
  if (!target || !isDashboardVisible(user, target)) return actionError("Dashboard não encontrado.");
  if (!canSetMyDefault(user, target)) {
    return actionError("Apenas dashboards seus e não compartilhados podem ser o seu padrão.");
  }

  const next = !target.isDefault;
  await prisma.$transaction(async (tx) => {
    if (next) {
      await tx.dashboard.updateMany({
        where: { campaignId: user.campaignId, ownerId: user.id, shared: false, isDefault: true, NOT: { id: target.id } },
        data: { isDefault: false },
      });
    }
    await tx.dashboard.update({ where: { id: target.id }, data: { isDefault: next } });
  });
  await audit({
    action: "dashboard.update",
    campaignId: user.campaignId,
    userId: user.id,
    entity: "Dashboard",
    entityId: target.id,
    details: { name: target.name, myDefault: next },
  });
  revalidateDashboards(target.id);
  return actionOk(next ? "Este agora é o seu dashboard inicial." : "O dashboard deixou de ser o seu padrão.", {
    isDefault: next,
  });
}

// ---------- Salvar (montador) ----------

const saveSchema = z.object({
  id: idSchema,
  name: nameSchema,
  description: descriptionSchema,
  shared: z.boolean().default(false),
  campaignDefault: z.boolean().default(false),
  widgets: dashboardWidgetsSchema,
});

export type SaveDashboardInput = z.input<typeof saveSchema>;

export async function saveDashboardAction(input: SaveDashboardInput): Promise<ActionResult<{ stillVisible: boolean }>> {
  const auth = await authorize("dashboard", "view");
  if (!auth.ok) return actionError(auth.error);
  const user = auth.user;

  const parsed = saveSchema.safeParse(input);
  if (!parsed.success) {
    // O montador mostra a mensagem em um toast: devolve o primeiro problema encontrado
    const result = zodToActionError(parsed.error);
    return { ...result, error: parsed.error.issues[0]?.message ?? result.error };
  }
  const data = parsed.data;

  const target = await findInCampaign(user.campaignId, data.id);
  if (!target || !isDashboardVisible(user, target)) return actionError("Dashboard não encontrado.");
  if (!canEditDashboard(user, target)) return actionError("Você não tem permissão para editar este dashboard.");

  const sharing = resolveSharing(user, target, { shared: data.shared, campaignDefault: data.campaignDefault });

  await prisma.$transaction(async (tx) => {
    if (sharing.shared && sharing.isDefault) {
      // Exatamente um padrão da campanha
      await tx.dashboard.updateMany({
        where: { campaignId: user.campaignId, shared: true, isDefault: true, NOT: { id: target.id } },
        data: { isDefault: false },
      });
    }
    await tx.dashboard.update({
      where: { id: target.id },
      data: {
        name: data.name,
        description: data.description,
        shared: sharing.shared,
        isDefault: sharing.isDefault,
        ownerId: sharing.ownerId,
        widgets: data.widgets as unknown as Prisma.InputJsonValue,
      },
    });
  });

  await audit({
    action: "dashboard.update",
    campaignId: user.campaignId,
    userId: user.id,
    entity: "Dashboard",
    entityId: target.id,
    details: {
      name: data.name,
      widgets: data.widgets.length,
      shared: sharing.shared,
      campaignDefault: sharing.shared && sharing.isDefault,
    },
  });
  revalidateDashboards(target.id);
  const stillVisible = sharing.shared || sharing.ownerId === user.id;
  return actionOk("Dashboard salvo.", { stillVisible });
}

// ---------- Dashboards padrão da campanha ----------

export async function createDefaultDashboardsAction(): Promise<ActionResult> {
  const auth = await authorize("admin");
  if (!auth.ok) return actionError(auth.error);
  const user = auth.user;

  const created = await prisma.$transaction(async (tx) => {
    const existing = await tx.dashboard.count({ where: { campaignId: user.campaignId } });
    if (existing > 0) return false;
    await createDefaultDashboards(tx, user.campaignId);
    return true;
  });
  if (!created) return actionError("A campanha já possui dashboards.");

  await audit({
    action: "dashboard.create",
    campaignId: user.campaignId,
    userId: user.id,
    entity: "Dashboard",
    details: { defaults: true },
  });
  revalidateDashboards();
  return actionOk("Dashboards padrão criados.");
}
