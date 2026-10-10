// Contadores dos disparos a partir das mensagens. Puro Node + Prisma (usado pelo worker, pelo
// processador da fila, pelas ações da tela e pelo webhook do WhatsApp).
import { prisma } from "@/lib/db";
import { countersFromGroups, shouldComplete, type BroadcastCounters } from "./logic";

/** Contagem atual das mensagens do disparo por status */
export async function loadBroadcastCounters(broadcastId: string): Promise<BroadcastCounters> {
  const rows = await prisma.broadcastMessage.groupBy({
    by: ["status"],
    where: { broadcastId },
    _count: { _all: true },
  });
  return countersFromGroups(rows.map((r) => ({ status: r.status, count: r._count._all })));
}

/**
 * Recalcula os contadores e conclui o disparo quando não há mais PENDING/SENDING.
 * Retorna true se o disparo foi concluído nesta chamada.
 */
export async function recomputeBroadcastCounters(broadcastId: string): Promise<boolean> {
  const broadcast = await prisma.broadcast.findUnique({ where: { id: broadcastId }, select: { status: true } });
  if (!broadcast) return false;
  const c = await loadBroadcastCounters(broadcastId);
  const data = { sentCount: c.sent, deliveredCount: c.delivered, readCount: c.read, failedCount: c.failed };

  if (shouldComplete(broadcast.status, c)) {
    // Atualização condicional: se alguém pausou/cancelou no meio tempo, não sobrescreve
    const done = await prisma.broadcast.updateMany({
      where: { id: broadcastId, status: "RUNNING" },
      data: { ...data, status: "COMPLETED", finishedAt: new Date() },
    });
    if (done.count === 1) return true;
  }
  await prisma.broadcast.updateMany({ where: { id: broadcastId }, data });
  return false;
}

/**
 * Recalcula sentCount/deliveredCount/readCount/failedCount do disparo a partir dos status
 * de BroadcastMessage e marca COMPLETED quando não houver mais mensagens PENDING/SENDING.
 */
export async function refreshBroadcastCounters(broadcastId: string): Promise<void> {
  await recomputeBroadcastCounters(broadcastId);
}
