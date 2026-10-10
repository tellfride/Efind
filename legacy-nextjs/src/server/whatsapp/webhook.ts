// Aplica os eventos normalizados dos webhooks: status das mensagens de disparo e mensagens recebidas
// (histórico + descadastro por "SAIR"). Puro Node + Prisma (sem next/*): usado pela rota do webhook
// e pelo simulador (inclusive dentro do worker).
import { prisma } from "@/lib/db";
import { refreshBroadcastCounters } from "@/server/messaging/counters";
import type { WebhookEvent } from "./types";
import { buildStatusUpdate, canonicalInboundPhone, inboundPhoneCandidates, isOptOutMessage, statusRank } from "./rules";

export interface ApplyWebhookResult {
  /** Eventos de status cuja mensagem foi encontrada na campanha */
  matched: number;
  /** Mensagens cujo status mudou */
  updated: number;
  /** Mensagens recebidas registradas */
  inbound: number;
  /** Eleitores descadastrados nesta chamada */
  optOuts: number;
}

type StatusEvent = Extract<WebhookEvent, { kind: "status" }>;
type InboundEvent = Extract<WebhookEvent, { kind: "inbound" }>;

const OPT_OUT_ERROR = "Descadastrado";

/** Descrição do erro para log, sem valores de consulta (que podem conter dados pessoais) */
function errorText(err: unknown): string {
  if (!(err instanceof Error)) return "erro desconhecido";
  if (err.name.startsWith("PrismaClient")) {
    const code = (err as Error & { code?: unknown }).code;
    return code ? `${err.name} ${String(code)}` : err.name;
  }
  return err.message;
}

async function applyStatus(campaignId: string, event: StatusEvent, touched: Set<string>): Promise<{ matched: boolean; updated: boolean }> {
  // Até duas tentativas: a atualização é condicional ao status lido (webhooks simultâneos do mesmo id)
  for (let attempt = 0; attempt < 2; attempt++) {
    const msg = await prisma.broadcastMessage.findFirst({
      where: { providerMessageId: event.providerMessageId, campaignId },
      select: { id: true, broadcastId: true, status: true, sentAt: true, deliveredAt: true, readAt: true },
    });
    if (!msg) return { matched: false, updated: false };
    const data = buildStatusUpdate(msg, event);
    if (!data) return { matched: true, updated: false };
    const res = await prisma.broadcastMessage.updateMany({ where: { id: msg.id, status: msg.status }, data });
    if (res.count > 0) {
      touched.add(msg.broadcastId);
      return { matched: true, updated: true };
    }
  }
  return { matched: true, updated: false };
}

async function applyInbound(
  connection: { id: string; campaignId: string },
  event: InboundEvent,
  touched: Set<string>,
): Promise<{ recorded: boolean; optedOut: boolean }> {
  const candidates = inboundPhoneCandidates(event.from);
  if (!candidates.length) return { recorded: false, optedOut: false };
  const { campaignId } = connection;

  const voter = await prisma.voter.findFirst({
    where: { campaignId, phone: { in: candidates } },
    select: { id: true, phone: true, optOutAt: true },
  });
  const isOptOut = isOptOutMessage(event.body);
  const body = event.body ? event.body.slice(0, 4096) : null;

  await prisma.inboundMessage.create({
    data: {
      campaignId,
      connectionId: connection.id,
      fromPhone: voter?.phone ?? canonicalInboundPhone(event.from),
      body,
      voterId: voter?.id ?? null,
      isOptOut,
      receivedAt: event.timestamp ?? new Date(),
    },
  });

  if (!isOptOut || !voter) return { recorded: true, optedOut: false };

  const pending = await prisma.broadcastMessage.findMany({
    where: { campaignId, voterId: voter.id, status: "PENDING" },
    select: { broadcastId: true },
    distinct: ["broadcastId"],
  });
  const alreadyOptedOut = !!voter.optOutAt;
  await prisma.$transaction([
    ...(alreadyOptedOut ? [] : [prisma.voter.update({ where: { id: voter.id }, data: { optOutAt: new Date() } })]),
    prisma.broadcastMessage.updateMany({
      where: { campaignId, voterId: voter.id, status: "PENDING" },
      data: { status: "SKIPPED", error: OPT_OUT_ERROR },
    }),
  ]);
  for (const p of pending) touched.add(p.broadcastId);

  if (!alreadyOptedOut) {
    // Auditoria sem dados pessoais (o webhook não tem usuário logado nem request do Next)
    await prisma.auditLog
      .create({
        data: {
          campaignId,
          action: "voter.opt_out",
          entity: "Voter",
          entityId: voter.id,
          details: { source: "whatsapp", connectionId: connection.id },
        },
      })
      .catch((err: unknown) => console.error("[whatsapp:webhook] falha ao auditar descadastro", errorText(err)));
  }
  return { recorded: true, optedOut: !alreadyOptedOut };
}

/**
 * Aplica eventos de webhook de uma conexão. Toda busca é restrita à campanha da conexão:
 * um provedor nunca altera mensagens ou eleitores de outra campanha.
 */
export async function applyWebhookEvents(
  connection: { id: string; campaignId: string },
  events: WebhookEvent[],
): Promise<ApplyWebhookResult> {
  const result: ApplyWebhookResult = { matched: 0, updated: 0, inbound: 0, optOuts: 0 };
  const touched = new Set<string>();

  const statuses = events
    .filter((e): e is StatusEvent => e.kind === "status")
    .sort((a, b) => statusRank(a.status) - statusRank(b.status));
  for (const event of statuses) {
    const r = await applyStatus(connection.campaignId, event, touched);
    if (r.matched) result.matched++;
    if (r.updated) result.updated++;
  }

  for (const event of events) {
    if (event.kind !== "inbound") continue;
    const r = await applyInbound(connection, event, touched);
    if (r.recorded) result.inbound++;
    if (r.optedOut) result.optOuts++;
  }

  for (const broadcastId of touched) {
    try {
      await refreshBroadcastCounters(broadcastId);
    } catch (err) {
      console.error("[whatsapp:webhook] falha ao atualizar contadores do disparo", errorText(err));
    }
  }
  return result;
}
