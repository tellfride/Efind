// Processador da fila de disparos. Puro Node + Prisma (sem next/*, sem @/lib/auth, sem @/lib/audit):
// roda no worker (scripts/worker.ts), em /api/cron/tick e no botão "Processar fila agora".
//
// Cada ciclo (runQueueTick):
//  1. devolve à fila mensagens presas em SENDING e encerra pendências de disparos cancelados;
//  2. materializa disparos agendados que venceram (gera uma mensagem por eleitor apto);
//  3. envia mensagens dos disparos em andamento respeitando o limite por minuto da conexão e do disparo;
//  4. atualiza os contadores e conclui disparos sem pendências;
//  5. (ciclo global) geocodifica alguns eleitores pendentes.
// Consentimento (MESSAGEABLE_WHERE) é exigido na materialização E conferido de novo no envio.
import { prisma, type Prisma } from "@/lib/db";
import { CAMPAIGN_ROLES, OFFICE_LABELS, type CampaignRole, type Office } from "@/lib/constants";
import { buildTemplateContext, renderTemplate, type TemplateContextSource } from "@/lib/template-vars";
import { voterFiltersSchema } from "@/lib/voter-filters";
import { buildVoterWhere, type ScopeUser } from "@/server/access";
import { processPendingGeocoding } from "@/server/geo/geocode";
import { getProviderDefinition, providerForConnection } from "@/server/whatsapp/registry";
import type { SendResult, WhatsAppProvider } from "@/server/whatsapp/types";
import { recomputeBroadcastCounters } from "./counters";
import {
  MAX_AUTO_ATTEMPTS,
  RATE_WINDOW_MS,
  STUCK_SENDING_MS,
  buildOutgoingMessage,
  chunk,
  computeSendBudget,
  recipientSkipReason,
  sendBlocker,
  truncateError,
} from "./logic";

export interface TickOptions {
  /** Restringe o ciclo a uma campanha (botão "Processar fila agora") */
  campaignId?: string;
  /** Máximo de mensagens processadas neste ciclo (padrão 100) */
  maxMessages?: number;
  now?: Date;
}

export interface TickReport {
  materialized: number;
  sent: number;
  failed: number;
  skipped: number;
  completed: number;
  /** Eleitores geocodificados (somente no ciclo global) */
  geocoded: number;
}

export type MaterializeResult =
  | { status: "RUNNING" | "COMPLETED"; recipients: number }
  | { status: "FAILED"; reason: string }
  /** Não estava mais agendado (outro processo já assumiu) */
  | { status: "SKIPPED" };

const DEFAULT_MAX_MESSAGES = 100;
const VOTER_PAGE = 2000;
const INSERT_CHUNK = 500;
const DUE_BATCH = 20;
const STATUS_RECHECK_EVERY = 10;
const MAX_CONSECUTIVE_TEMP_ERRORS = 3;

/** Auditoria direta no banco (o helper audit() depende de next/headers) */
async function writeAudit(data: {
  action: string;
  campaignId: string;
  userId?: string | null;
  entityId: string;
  details: Record<string, unknown>;
}): Promise<void> {
  try {
    await prisma.auditLog.create({
      data: {
        action: data.action,
        campaignId: data.campaignId,
        userId: data.userId ?? null,
        entity: "Broadcast",
        entityId: data.entityId,
        details: data.details as Prisma.InputJsonValue,
      },
    });
  } catch (err) {
    console.error("[disparos] falha ao registrar auditoria", data.action, err instanceof Error ? err.message : "");
  }
}

function campaignContext(c: { ballotName: string; ballotNumber: string | null; party: string | null; office: string }) {
  return {
    ballotName: c.ballotName,
    ballotNumber: c.ballotNumber,
    party: c.party,
    officeLabel: OFFICE_LABELS[c.office as Office] ?? c.office,
  } satisfies TemplateContextSource["campaign"];
}

/**
 * Gera as mensagens (uma por telefone) de um disparo SCHEDULED e o coloca em RUNNING
 * (ou COMPLETED, se ninguém estiver apto). O público é sempre limitado ao escopo de quem criou
 * o disparo e somente a eleitores que consentiram (messageable forçado).
 */
export async function materializeBroadcast(broadcastId: string, opts: { now?: Date } = {}): Promise<MaterializeResult> {
  const now = opts.now ?? new Date();
  const b = await prisma.broadcast.findUnique({
    where: { id: broadcastId },
    include: {
      template: true,
      campaign: { select: { ballotName: true, ballotNumber: true, party: true, office: true, status: true } },
      createdBy: { select: { id: true, role: true, campaignId: true, active: true } },
    },
  });
  if (!b || b.status !== "SCHEDULED") return { status: "SKIPPED" };

  const fail = async (reason: string): Promise<MaterializeResult> => {
    const r = await prisma.broadcast.updateMany({
      where: { id: b.id, status: "SCHEDULED" },
      data: { status: "FAILED", finishedAt: now },
    });
    if (r.count !== 1) return { status: "SKIPPED" };
    await writeAudit({ action: "broadcast.fail", campaignId: b.campaignId, entityId: b.id, details: { automatic: true, reason } });
    return { status: "FAILED", reason };
  };

  const creator = b.createdBy;
  if (
    !creator ||
    !creator.active ||
    creator.campaignId !== b.campaignId ||
    !(CAMPAIGN_ROLES as readonly string[]).includes(creator.role)
  ) {
    return fail("O usuário que criou o disparo foi desativado ou removido.");
  }
  if (b.campaign.status !== "ACTIVE") return fail("A campanha está suspensa.");
  if (!b.template || b.template.campaignId !== b.campaignId) return fail("O modelo de mensagem foi excluído.");
  const parsed = voterFiltersSchema.safeParse(b.filters ?? {});
  // Filtros inválidos NUNCA viram "todos os eleitores"
  if (!parsed.success) return fail("Os filtros do público são inválidos.");

  const scopeUser: ScopeUser = { id: creator.id, role: creator.role as CampaignRole, campaignId: b.campaignId };
  const where = await buildVoterWhere(scopeUser, { ...parsed.data, messageable: true });
  const campaign = campaignContext(b.campaign);
  const body = b.template.body;

  const rows: Prisma.BroadcastMessageCreateManyInput[] = [];
  const phones = new Set<string>();
  let cursor: string | undefined;
  for (;;) {
    const page = await prisma.voter.findMany({
      where: cursor ? { AND: [where, { id: { gt: cursor } }] } : where,
      orderBy: { id: "asc" },
      take: VOTER_PAGE,
      select: {
        id: true,
        name: true,
        phone: true,
        neighborhood: true,
        city: true,
        registeredBy: { select: { name: true } },
      },
    });
    for (const v of page) {
      if (phones.has(v.phone)) continue;
      phones.add(v.phone);
      rows.push({
        broadcastId: b.id,
        campaignId: b.campaignId,
        voterId: v.id,
        phone: v.phone,
        renderedBody: renderTemplate(body, buildTemplateContext({ voter: v, campaign, registeredBy: v.registeredBy })),
        status: "PENDING",
      });
    }
    if (page.length < VOTER_PAGE) break;
    cursor = page[page.length - 1].id;
  }

  const total = rows.length;
  // Assume o disparo e grava as mensagens numa transação: ninguém vê RUNNING sem as mensagens
  const claimed = await prisma.$transaction(
    async (tx) => {
      const r = await tx.broadcast.updateMany({
        where: { id: b.id, status: "SCHEDULED" },
        data:
          total > 0
            ? { status: "RUNNING", startedAt: now, finishedAt: null, totalRecipients: total }
            : { status: "COMPLETED", startedAt: now, finishedAt: now, totalRecipients: 0 },
      });
      if (r.count !== 1) return false;
      for (const part of chunk(rows, INSERT_CHUNK)) await tx.broadcastMessage.createMany({ data: part });
      return true;
    },
    { maxWait: 15_000, timeout: 120_000 },
  );
  if (!claimed) return { status: "SKIPPED" };
  return { status: total > 0 ? "RUNNING" : "COMPLETED", recipients: total };
}

/** Pausa automaticamente um disparo que não pode enviar, registrando o motivo */
async function autoPause(b: { id: string; campaignId: string }, reason: string): Promise<void> {
  const r = await prisma.broadcast.updateMany({ where: { id: b.id, status: "RUNNING" }, data: { status: "PAUSED" } });
  if (r.count === 1) {
    await writeAudit({ action: "broadcast.pause", campaignId: b.campaignId, entityId: b.id, details: { automatic: true, reason } });
  }
}

type RunningBroadcast = Prisma.BroadcastGetPayload<{
  include: {
    template: true;
    connection: true;
    campaign: { select: { ballotName: true; ballotNumber: true; party: true; office: true } };
  };
}>;

interface SendState {
  now: Date;
  remaining: number;
  report: TickReport;
  providers: Map<string, WhatsAppProvider | null>;
  /** Mensagens enviadas por conexão na janela de 1 minuto (banco + este ciclo) */
  connectionUsage: Map<string, number>;
}

async function sendForBroadcast(b: RunningBroadcast, state: SendState): Promise<void> {
  const def = b.connection ? getProviderDefinition(b.connection.provider) : null;
  const blocker = sendBlocker({
    connection: b.connection,
    campaignId: b.campaignId,
    providerKnown: !!def,
    requiresApprovedTemplate: !!def?.requiresApprovedTemplate,
    template: b.template,
  });
  if (blocker || !b.connection || !def) {
    await autoPause(b, blocker?.message ?? "Conexão de WhatsApp indisponível.");
    return;
  }
  const connection = b.connection;

  if (!state.providers.has(connection.id)) {
    let instance: WhatsAppProvider | null = null;
    try {
      instance = providerForConnection(connection);
    } catch {
      instance = null;
    }
    state.providers.set(connection.id, instance);
  }
  const provider = state.providers.get(connection.id);
  if (!provider) {
    await autoPause(b, "Não foi possível carregar as credenciais da conexão de WhatsApp.");
    return;
  }

  const windowStart = new Date(state.now.getTime() - RATE_WINDOW_MS);
  if (!state.connectionUsage.has(connection.id)) {
    const used = await prisma.broadcastMessage.count({
      where: { sentAt: { gte: windowStart }, broadcast: { is: { connectionId: connection.id } } },
    });
    state.connectionUsage.set(connection.id, used);
  }
  const ownSent = await prisma.broadcastMessage.count({ where: { broadcastId: b.id, sentAt: { gte: windowStart } } });
  const budget = computeSendBudget({
    connectionRate: connection.ratePerMinute,
    connectionSentLastMinute: state.connectionUsage.get(connection.id) ?? 0,
    broadcastRate: b.ratePerMinute,
    broadcastSentLastMinute: ownSent,
    tickRemaining: state.remaining,
  });
  if (budget <= 0) return;

  const pending = await prisma.broadcastMessage.findMany({
    where: { broadcastId: b.id, status: "PENDING" },
    orderBy: [{ createdAt: "asc" }, { id: "asc" }],
    take: budget,
    select: {
      id: true,
      phone: true,
      renderedBody: true,
      campaignId: true,
      attempts: true,
      voter: {
        select: {
          campaignId: true,
          phone: true,
          name: true,
          neighborhood: true,
          city: true,
          whatsappOptIn: true,
          optOutAt: true,
          consentAt: true,
          registeredBy: { select: { name: true } },
        },
      },
    },
  });

  const campaign = campaignContext(b.campaign);
  let processed = 0;
  let tempErrors = 0;
  for (const m of pending) {
    if (state.remaining <= 0) break;
    // Respeita pausa/cancelamento feitos durante o envio
    if (processed > 0 && processed % STATUS_RECHECK_EVERY === 0) {
      const current = await prisma.broadcast.findUnique({ where: { id: b.id }, select: { status: true } });
      if (current?.status !== "RUNNING") break;
    }
    processed++;

    // Reserva atômica: só um processo envia cada mensagem
    const claim = await prisma.broadcastMessage.updateMany({
      where: { id: m.id, status: "PENDING" },
      data: { status: "SENDING", attempts: { increment: 1 } },
    });
    if (claim.count !== 1) continue;
    state.remaining--;
    const attempts = m.attempts + 1;

    const skipReason = recipientSkipReason(m.voter, m);
    if (skipReason || !m.voter) {
      await prisma.broadcastMessage.updateMany({
        where: { id: m.id, status: "SENDING" },
        data: { status: "SKIPPED", error: skipReason ?? "Eleitor excluído" },
      });
      state.report.skipped++;
      continue;
    }

    const context = buildTemplateContext({ voter: m.voter, campaign, registeredBy: m.voter.registeredBy });
    const outgoing = buildOutgoingMessage({
      to: m.phone,
      renderedBody: m.renderedBody,
      template: b.template,
      requiresApprovedTemplate: def.requiresApprovedTemplate,
      context,
    });

    let result: SendResult;
    try {
      result = await provider.send(outgoing);
    } catch (err) {
      result = { ok: false, error: truncateError(err), retryable: true };
    }

    if (result.ok) {
      tempErrors = 0;
      const sentAt = new Date();
      const updated = await prisma.broadcastMessage.updateMany({
        where: { id: m.id, status: "SENDING" },
        data: { status: "SENT", sentAt, providerMessageId: result.providerMessageId ?? null, error: null },
      });
      if (updated.count === 0) {
        // Status já avançou (ex.: webhook de entrega): só completa os dados do envio
        await prisma.broadcastMessage.updateMany({
          where: { id: m.id, sentAt: null },
          data: { sentAt, providerMessageId: result.providerMessageId ?? null },
        });
      }
      state.connectionUsage.set(connection.id, (state.connectionUsage.get(connection.id) ?? 0) + 1);
      state.report.sent++;
      continue;
    }

    const retry = !!result.retryable && attempts < MAX_AUTO_ATTEMPTS;
    await prisma.broadcastMessage.updateMany({
      where: { id: m.id, status: "SENDING" },
      data: { status: retry ? "PENDING" : "FAILED", error: truncateError(result.error ?? "Falha no envio") },
    });
    if (!retry) state.report.failed++;
    if (result.retryable) {
      // Erros temporários seguidos (limite do provedor, instabilidade): tenta no próximo ciclo
      tempErrors++;
      if (tempErrors >= MAX_CONSECUTIVE_TEMP_ERRORS) break;
    } else {
      tempErrors = 0;
    }
  }
}

/** Um ciclo da fila. Seguro para rodar em paralelo (worker + cron): reservas são atômicas. */
export async function runQueueTick(opts: TickOptions = {}): Promise<TickReport> {
  const now = opts.now ?? new Date();
  const maxMessages = Math.max(0, Math.floor(opts.maxMessages ?? DEFAULT_MAX_MESSAGES));
  const report: TickReport = { materialized: 0, sent: 0, failed: 0, skipped: 0, completed: 0, geocoded: 0 };
  const scope = opts.campaignId ? { campaignId: opts.campaignId } : {};
  const touched = new Set<string>();

  // 1) Mensagens presas em SENDING (processo interrompido) e pendências de disparos cancelados
  const stuckBefore = new Date(now.getTime() - STUCK_SENDING_MS);
  const stuckWhere: Prisma.BroadcastMessageWhereInput = { ...scope, status: "SENDING", updatedAt: { lt: stuckBefore } };
  const stuck = await prisma.broadcastMessage.findMany({
    where: stuckWhere,
    select: { broadcastId: true },
    distinct: ["broadcastId"],
  });
  if (stuck.length) {
    await prisma.broadcastMessage.updateMany({
      where: { ...stuckWhere, attempts: { gte: MAX_AUTO_ATTEMPTS } },
      data: { status: "FAILED", error: "Sem confirmação do provedor após várias tentativas." },
    });
    await prisma.broadcastMessage.updateMany({ where: stuckWhere, data: { status: "PENDING" } });
    stuck.forEach((s) => touched.add(s.broadcastId));
  }
  const orphanWhere: Prisma.BroadcastMessageWhereInput = {
    ...scope,
    status: "PENDING",
    broadcast: { is: { status: { in: ["CANCELLED", "FAILED"] } } },
  };
  const orphans = await prisma.broadcastMessage.findMany({ where: orphanWhere, select: { broadcastId: true }, distinct: ["broadcastId"] });
  if (orphans.length) {
    await prisma.broadcastMessage.updateMany({ where: orphanWhere, data: { status: "SKIPPED", error: "Cancelado" } });
    orphans.forEach((o) => touched.add(o.broadcastId));
  }

  // 2) Agendados que venceram
  const due = await prisma.broadcast.findMany({
    where: { ...scope, status: "SCHEDULED", scheduledAt: { lte: now }, campaign: { is: { status: "ACTIVE" } } },
    orderBy: { scheduledAt: "asc" },
    take: DUE_BATCH,
    select: { id: true, campaignId: true },
  });
  for (const d of due) {
    try {
      const result = await materializeBroadcast(d.id, { now });
      if (result.status === "RUNNING" || result.status === "COMPLETED") {
        report.materialized++;
        if (result.status === "COMPLETED") report.completed++;
        await writeAudit({
          action: "broadcast.start",
          campaignId: d.campaignId,
          entityId: d.id,
          details: { automatic: true, recipients: result.recipients },
        });
      }
    } catch (err) {
      console.error("[disparos] falha ao preparar disparo agendado", d.id, err instanceof Error ? err.message : "");
    }
  }

  // 3) Envio
  if (maxMessages > 0) {
    const running = await prisma.broadcast.findMany({
      where: { ...scope, status: "RUNNING", campaign: { is: { status: "ACTIVE" } } },
      orderBy: [{ startedAt: "asc" }, { createdAt: "asc" }],
      include: {
        template: true,
        connection: true,
        campaign: { select: { ballotName: true, ballotNumber: true, party: true, office: true } },
      },
    });
    const state: SendState = { now, remaining: maxMessages, report, providers: new Map(), connectionUsage: new Map() };
    for (const b of running) {
      if (state.remaining <= 0) break;
      touched.add(b.id);
      try {
        await sendForBroadcast(b, state);
      } catch (err) {
        console.error("[disparos] falha ao enviar disparo", b.id, err instanceof Error ? err.message : "");
      }
    }
  }

  // 4) Contadores
  for (const id of touched) {
    try {
      if (await recomputeBroadcastCounters(id)) report.completed++;
    } catch (err) {
      console.error("[disparos] falha ao atualizar contadores", id, err instanceof Error ? err.message : "");
    }
  }

  // 5) Geocodificação pendente (somente no ciclo global do worker/cron)
  if (!opts.campaignId) {
    try {
      report.geocoded = await processPendingGeocoding(5);
    } catch (err) {
      console.error("[geocode] falha no ciclo", err instanceof Error ? err.message : "");
    }
  }

  return report;
}

/** O ciclo fez alguma coisa? (para logs resumidos) */
export function tickHadActivity(r: TickReport): boolean {
  return r.materialized + r.sent + r.failed + r.skipped + r.completed + r.geocoded > 0;
}
