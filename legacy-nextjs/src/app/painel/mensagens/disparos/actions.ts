"use server";

// Ações dos disparos: criar (assistente), pausar/retomar/cancelar/reenviar falhas, excluir e
// processar a fila manualmente (ADMIN). Visibilidade: ADMIN vê todos; os demais, os que criaram.
import { revalidatePath } from "next/cache";
import { z } from "zod";
import { prisma, type Prisma } from "@/lib/db";
import { authorize } from "@/lib/auth";
import { audit } from "@/lib/audit";
import { actionError, actionOk, zodToActionError, type ActionResult } from "@/lib/action-result";
import { BROADCAST_STATUS_LABELS, type BroadcastStatus } from "@/lib/constants";
import { cleanVoterFilters } from "@/lib/voter-filters";
import { formatDateTime, formatNumber } from "@/lib/utils";
import { buildVoterWhere } from "@/server/access";
import { validateSchedule } from "@/components/messaging/schedule";
import { broadcastInputSchema, parseFiltersField } from "@/server/messaging/broadcast-schema";
import { refreshBroadcastCounters } from "@/server/messaging/counters";
import { MAX_MANUAL_ATTEMPTS, allowedFrom, canDeleteBroadcast, nextBroadcastStatus, type BroadcastControl } from "@/server/messaging/logic";
import { materializeBroadcast, runQueueTick, type TickReport } from "@/server/messaging/processor";
import { broadcastScopeWhere, broadcastSendProblem, filterIdsInScope, findBroadcastInScope } from "@/server/messaging/queries";

const LIST_PATH = "/painel/mensagens/disparos";
const idSchema = z.string().trim().min(1).max(64);
const controlSchema = z.enum(["pause", "resume", "cancel", "retry"]);

function statusLabel(status: string): string {
  return (BROADCAST_STATUS_LABELS[status as BroadcastStatus] ?? status).toLowerCase();
}

function revalidateBroadcast(id?: string) {
  revalidatePath(LIST_PATH);
  if (id) revalidatePath(`${LIST_PATH}/${id}`);
}

/** Cria o disparo (agendado ou imediato) a partir do assistente */
export async function createBroadcastAction(
  _prev: ActionResult<{ id: string }>,
  formData: FormData,
): Promise<ActionResult<{ id: string }>> {
  const auth = await authorize("disparos", "create");
  if (!auth.ok) return actionError(auth.error);
  const user = auth.user;

  const text = (key: string) => {
    const v = formData.get(key);
    return typeof v === "string" ? v : undefined;
  };
  const filtersRaw = parseFiltersField(formData.get("filters"));
  if (filtersRaw === null) return actionError("Os filtros do público são inválidos.");
  const parsed = broadcastInputSchema.safeParse({
    name: text("name") ?? "",
    templateId: text("templateId") ?? "",
    connectionId: text("connectionId") ?? "",
    ratePerMinute: text("ratePerMinute"),
    mode: text("mode"),
    scheduledAt: text("scheduledAt") || undefined,
    filters: filtersRaw,
    consent: text("consent"),
  });
  if (!parsed.success) return zodToActionError(parsed.error);
  const d = parsed.data;

  // "messageable" é sempre forçado na materialização; não fica salvo nos filtros
  const filters = cleanVoterFilters({ ...d.filters, messageable: undefined });
  if (!(await filterIdsInScope(user, filters))) {
    return actionError("Os filtros de equipe selecionados não pertencem à sua rede.");
  }

  const [template, connection] = await Promise.all([
    prisma.messageTemplate.findFirst({ where: { id: d.templateId, campaignId: user.campaignId } }),
    prisma.whatsAppConnection.findFirst({ where: { id: d.connectionId, campaignId: user.campaignId } }),
  ]);
  if (!template) return actionError("Modelo de mensagem não encontrado.", { templateId: ["Escolha outro modelo"] });
  if (!connection) return actionError("Conexão de WhatsApp não encontrada.", { connectionId: ["Escolha outra conexão"] });
  const problem = broadcastSendProblem({ campaignId: user.campaignId, connection, template });
  if (problem) return actionError(problem);
  if (d.ratePerMinute > connection.ratePerMinute) {
    const msg = `O limite desta conexão é de ${connection.ratePerMinute} mensagens por minuto.`;
    return actionError(msg, { ratePerMinute: [msg] });
  }

  let scheduledAt = new Date();
  if (d.mode === "schedule") {
    const v = validateSchedule(d.scheduledAt);
    if (!v.ok) return actionError(v.error, { scheduledAt: [v.error] });
    scheduledAt = v.date;
  }

  const eligible = await prisma.voter.count({ where: await buildVoterWhere(user, { ...filters, messageable: true }) });
  if (eligible === 0) {
    return actionError("Nenhum eleitor deste público autorizou receber mensagens pelo WhatsApp. Ajuste os filtros.");
  }

  const broadcast = await prisma.broadcast.create({
    data: {
      campaignId: user.campaignId,
      name: d.name,
      templateId: template.id,
      connectionId: connection.id,
      createdById: user.id,
      status: "SCHEDULED",
      filters: filters as Prisma.InputJsonValue,
      scheduledAt,
      ratePerMinute: d.ratePerMinute,
      // Estimativa; o número exato é gravado quando as mensagens são geradas
      totalRecipients: eligible,
    },
    select: { id: true },
  });
  await audit({
    action: "broadcast.create",
    campaignId: user.campaignId,
    userId: user.id,
    entity: "Broadcast",
    entityId: broadcast.id,
    details: {
      name: d.name,
      templateId: template.id,
      connectionId: connection.id,
      mode: d.mode,
      scheduledAt: scheduledAt.toISOString(),
      ratePerMinute: d.ratePerMinute,
      estimatedRecipients: eligible,
    },
  });

  if (d.mode === "schedule") {
    revalidateBroadcast(broadcast.id);
    return actionOk(`Disparo agendado para ${formatDateTime(scheduledAt)}.`, { id: broadcast.id });
  }

  const result = await materializeBroadcast(broadcast.id);
  revalidateBroadcast(broadcast.id);
  if (result.status === "FAILED") {
    return actionOk(`Disparo criado, mas não pôde ser iniciado: ${result.reason}`, { id: broadcast.id });
  }
  if (result.status === "RUNNING" || result.status === "COMPLETED") {
    await audit({
      action: "broadcast.start",
      campaignId: user.campaignId,
      userId: user.id,
      entity: "Broadcast",
      entityId: broadcast.id,
      details: { recipients: result.recipients },
    });
    if (result.status === "COMPLETED") {
      return actionOk("Disparo criado, mas nenhum eleitor estava apto no momento do envio.", { id: broadcast.id });
    }
    return actionOk(`Disparo iniciado para ${formatNumber(result.recipients)} eleitores.`, { id: broadcast.id });
  }
  return actionOk("Disparo criado.", { id: broadcast.id });
}

const CONTROL_VERBS: Record<BroadcastControl, string> = {
  pause: "pausar",
  resume: "retomar",
  cancel: "cancelar",
  retry: "reenviar as falhas de",
};

/** Pausar, retomar, cancelar ou reenviar falhas */
export async function controlBroadcastAction(broadcastId: string, control: BroadcastControl): Promise<ActionResult> {
  const auth = await authorize("disparos", "edit");
  if (!auth.ok) return actionError(auth.error);
  const user = auth.user;
  const id = idSchema.safeParse(broadcastId);
  const action = controlSchema.safeParse(control);
  if (!id.success || !action.success) return actionError("Ação inválida.");

  const b = await findBroadcastInScope(user, id.data);
  if (!b) return actionError("Disparo não encontrado.");
  const next = nextBroadcastStatus(b.status, action.data);
  if (!next) {
    return actionError(`Não é possível ${CONTROL_VERBS[action.data]} um disparo ${statusLabel(b.status)}.`);
  }
  const changed = "O status do disparo mudou. Atualize a página e tente novamente.";
  const now = new Date();

  switch (action.data) {
    case "pause": {
      const r = await prisma.broadcast.updateMany({
        where: { id: b.id, status: { in: allowedFrom("pause") } },
        data: { status: "PAUSED" },
      });
      if (r.count !== 1) return actionError(changed);
      await audit({ action: "broadcast.pause", campaignId: user.campaignId, userId: user.id, entity: "Broadcast", entityId: b.id });
      revalidateBroadcast(b.id);
      return actionOk("Disparo pausado. As mensagens na fila aguardam até você retomar.");
    }
    case "resume": {
      const problem = broadcastSendProblem(b);
      if (problem) return actionError(problem);
      const r = await prisma.broadcast.updateMany({
        where: { id: b.id, status: { in: allowedFrom("resume") } },
        data: { status: "RUNNING", finishedAt: null },
      });
      if (r.count !== 1) return actionError(changed);
      await audit({ action: "broadcast.resume", campaignId: user.campaignId, userId: user.id, entity: "Broadcast", entityId: b.id });
      await refreshBroadcastCounters(b.id);
      revalidateBroadcast(b.id);
      return actionOk("Disparo retomado.");
    }
    case "cancel": {
      const skipped = await prisma.$transaction(async (tx) => {
        const r = await tx.broadcast.updateMany({
          where: { id: b.id, status: { in: allowedFrom("cancel") } },
          data: { status: "CANCELLED", finishedAt: now },
        });
        if (r.count !== 1) return -1;
        const m = await tx.broadcastMessage.updateMany({
          where: { broadcastId: b.id, status: "PENDING" },
          data: { status: "SKIPPED", error: "Cancelado" },
        });
        return m.count;
      });
      if (skipped < 0) return actionError(changed);
      await audit({
        action: "broadcast.cancel",
        campaignId: user.campaignId,
        userId: user.id,
        entity: "Broadcast",
        entityId: b.id,
        details: { previousStatus: b.status, skippedMessages: skipped },
      });
      await refreshBroadcastCounters(b.id);
      revalidateBroadcast(b.id);
      return actionOk(
        skipped > 0 ? `Disparo cancelado. ${formatNumber(skipped)} mensagens da fila não serão enviadas.` : "Disparo cancelado.",
      );
    }
    case "retry": {
      const problem = broadcastSendProblem(b);
      if (problem) return actionError(problem);
      const requeued = await prisma.$transaction(async (tx) => {
        const r = await tx.broadcast.updateMany({
          where: { id: b.id, status: { in: allowedFrom("retry") } },
          data: { status: "RUNNING", finishedAt: null },
        });
        if (r.count !== 1) return -1;
        const m = await tx.broadcastMessage.updateMany({
          where: { broadcastId: b.id, status: "FAILED", attempts: { lt: MAX_MANUAL_ATTEMPTS } },
          data: { status: "PENDING", error: null },
        });
        if (m.count === 0) throw new NothingToRetry();
        return m.count;
      }).catch((err: unknown) => {
        if (err instanceof NothingToRetry) return 0;
        throw err;
      });
      if (requeued < 0) return actionError(changed);
      if (requeued === 0) {
        return actionError(`Não há falhas para reenviar (cada mensagem pode ser tentada até ${MAX_MANUAL_ATTEMPTS} vezes).`);
      }
      await audit({
        action: "broadcast.retry",
        campaignId: user.campaignId,
        userId: user.id,
        entity: "Broadcast",
        entityId: b.id,
        details: { requeuedMessages: requeued },
      });
      await refreshBroadcastCounters(b.id);
      revalidateBroadcast(b.id);
      return actionOk(`${formatNumber(requeued)} mensagens voltaram para a fila.`);
    }
  }
}

class NothingToRetry extends Error {}

/** Exclui o disparo e suas mensagens (não vale para disparo em andamento) */
export async function deleteBroadcastAction(broadcastId: string): Promise<ActionResult> {
  const auth = await authorize("disparos", "delete");
  if (!auth.ok) return actionError(auth.error);
  const user = auth.user;
  const id = idSchema.safeParse(broadcastId);
  if (!id.success) return actionError("Disparo não encontrado.");

  const b = await findBroadcastInScope(user, id.data);
  if (!b) return actionError("Disparo não encontrado.");
  if (!canDeleteBroadcast(b.status)) return actionError("Pause ou cancele o disparo antes de excluí-lo.");

  const r = await prisma.broadcast.deleteMany({
    where: { AND: [broadcastScopeWhere(user), { id: b.id, status: { not: "RUNNING" } }] },
  });
  if (r.count !== 1) return actionError("O status do disparo mudou. Atualize a página e tente novamente.");
  await audit({
    action: "broadcast.delete",
    campaignId: user.campaignId,
    userId: user.id,
    entity: "Broadcast",
    entityId: b.id,
    details: { name: b.name, status: b.status, totalRecipients: b.totalRecipients, sentCount: b.sentCount },
  });
  revalidatePath(LIST_PATH);
  return actionOk("Disparo excluído.");
}

/** Processa a fila da campanha agora (útil sem o worker rodando). Somente ADMIN. */
export async function processQueueNowAction(): Promise<ActionResult<TickReport>> {
  const auth = await authorize("admin");
  if (!auth.ok) return actionError(auth.error);
  const user = auth.user;
  const report = await runQueueTick({ campaignId: user.campaignId, maxMessages: 50 });
  await audit({
    action: "broadcast.process_queue",
    campaignId: user.campaignId,
    userId: user.id,
    entity: "Broadcast",
    details: { ...report },
  });
  revalidatePath(LIST_PATH, "layout");
  const parts = [
    report.materialized && `${formatNumber(report.materialized)} disparo(s) iniciado(s)`,
    report.sent && `${formatNumber(report.sent)} enviada(s)`,
    report.failed && `${formatNumber(report.failed)} falha(s)`,
    report.skipped && `${formatNumber(report.skipped)} ignorada(s)`,
    report.completed && `${formatNumber(report.completed)} concluído(s)`,
  ].filter(Boolean);
  return actionOk(parts.length ? `Fila processada: ${parts.join(", ")}.` : "Nada a processar agora (fila vazia ou limite por minuto atingido).", report);
}
