// Regras puras dos disparos (sem banco): orçamento de envio, contadores, máquina de estados,
// parâmetros de template oficial e montagem da mensagem. Coberto por tests/messaging*.test.ts.
import { TEMPLATE_VARIABLES, type TemplateContext, type TemplateVariableKey } from "@/lib/template-vars";
import type { BroadcastStatus, MessageStatus } from "@/lib/constants";
import type { OutgoingMessage } from "@/server/whatsapp/types";

/** Tentativas automáticas (erros temporários) antes de marcar a mensagem como FAILED */
export const MAX_AUTO_ATTEMPTS = 3;
/** Limite total de tentativas, contando os reenvios manuais ("Reenviar falhas") */
export const MAX_MANUAL_ATTEMPTS = 5;
/** Mensagens presas em SENDING por mais que isso voltam para a fila */
export const STUCK_SENDING_MS = 5 * 60_000;
/** Janela do limite de envio por minuto */
export const RATE_WINDOW_MS = 60_000;

/** Status de disparo que impedem excluir o modelo usado */
export const TEMPLATE_LOCKING_STATUSES: BroadcastStatus[] = ["SCHEDULED", "RUNNING", "PAUSED"];
/** Status em que a tela se atualiza sozinha */
export const ACTIVE_BROADCAST_STATUSES: BroadcastStatus[] = ["SCHEDULED", "RUNNING"];

export function isActiveBroadcast(status: string): boolean {
  return (ACTIVE_BROADCAST_STATUSES as string[]).includes(status);
}

// ---------- Orçamento de envio ----------

export interface SendBudgetInput {
  /** Limite da conexão (mensagens/minuto) */
  connectionRate: number;
  /** Mensagens enviadas pela conexão (todos os disparos) nos últimos 60 s */
  connectionSentLastMinute: number;
  /** Limite escolhido para o disparo */
  broadcastRate: number;
  /** Mensagens enviadas por este disparo nos últimos 60 s */
  broadcastSentLastMinute: number;
  /** Quanto ainda cabe neste ciclo (maxMessages - já processadas) */
  tickRemaining: number;
}

/** Quantas mensagens o disparo pode enviar agora (nunca negativo) */
export function computeSendBudget(i: SendBudgetInput): number {
  const conn = Math.max(0, Math.floor(i.connectionRate) - i.connectionSentLastMinute);
  const own = Math.max(0, Math.min(Math.floor(i.broadcastRate), Math.floor(i.connectionRate)) - i.broadcastSentLastMinute);
  return Math.max(0, Math.min(conn, own, Math.floor(i.tickRemaining)));
}

// ---------- Contadores ----------

export interface StatusCountRow {
  status: string;
  count: number;
}

export interface BroadcastCounters {
  total: number;
  pending: number;
  sending: number;
  /** PENDING + SENDING */
  queued: number;
  /** SENT + DELIVERED + READ */
  sent: number;
  /** DELIVERED + READ */
  delivered: number;
  read: number;
  failed: number;
  skipped: number;
  /** sent + failed + skipped (já processadas) */
  processed: number;
}

/** Converte o groupBy de BroadcastMessage por status nos contadores do disparo */
export function countersFromGroups(rows: StatusCountRow[]): BroadcastCounters {
  const by: Partial<Record<MessageStatus, number>> = {};
  let total = 0;
  for (const r of rows) {
    by[r.status as MessageStatus] = (by[r.status as MessageStatus] ?? 0) + r.count;
    total += r.count;
  }
  const n = (s: MessageStatus) => by[s] ?? 0;
  const sent = n("SENT") + n("DELIVERED") + n("READ");
  const failed = n("FAILED");
  const skipped = n("SKIPPED");
  return {
    total,
    pending: n("PENDING"),
    sending: n("SENDING"),
    queued: n("PENDING") + n("SENDING"),
    sent,
    delivered: n("DELIVERED") + n("READ"),
    read: n("READ"),
    failed,
    skipped,
    processed: sent + failed + skipped,
  };
}

/** Disparo em andamento sem nada na fila → concluído */
export function shouldComplete(status: string, c: Pick<BroadcastCounters, "pending" | "sending">): boolean {
  return status === "RUNNING" && c.pending + c.sending === 0;
}

/** Percentual (0–100) com proteção para divisão por zero */
export function percent(part: number, whole: number): number {
  if (!whole || whole <= 0) return 0;
  return Math.min(100, Math.max(0, (part / whole) * 100));
}

/** Taxas exibidas: entregues sobre enviadas; lidas sobre entregues */
export function broadcastRates(c: { sent: number; delivered: number; read: number }) {
  return { delivery: percent(c.delivered, c.sent), read: percent(c.read, c.delivered) };
}

// ---------- Máquina de estados ----------

export type BroadcastControl = "pause" | "resume" | "cancel" | "retry";

const TRANSITIONS: Record<BroadcastControl, { from: BroadcastStatus[]; to: BroadcastStatus }> = {
  pause: { from: ["RUNNING"], to: "PAUSED" },
  resume: { from: ["PAUSED"], to: "RUNNING" },
  cancel: { from: ["SCHEDULED", "RUNNING", "PAUSED"], to: "CANCELLED" },
  retry: { from: ["RUNNING", "COMPLETED"], to: "RUNNING" },
};

/** Status de origem aceitos por uma ação (usado no where das atualizações atômicas) */
export function allowedFrom(control: BroadcastControl): BroadcastStatus[] {
  return [...TRANSITIONS[control].from];
}

/** Próximo status ao aplicar a ação, ou null se a ação não vale no status atual */
export function nextBroadcastStatus(status: string, control: BroadcastControl): BroadcastStatus | null {
  const t = TRANSITIONS[control];
  return (t.from as string[]).includes(status) ? t.to : null;
}

/** Disparo em andamento não pode ser excluído (pause ou cancele antes) */
export function canDeleteBroadcast(status: string): boolean {
  return status !== "RUNNING";
}

export interface AvailableActions {
  pause: boolean;
  resume: boolean;
  cancel: boolean;
  retry: boolean;
  delete: boolean;
}

/** Ações disponíveis na tela de detalhe conforme status e permissões */
export function availableBroadcastActions(
  status: string,
  opts: { retryableFailures: number; canEdit: boolean; canDelete: boolean },
): AvailableActions {
  const ok = (c: BroadcastControl) => opts.canEdit && nextBroadcastStatus(status, c) !== null;
  return {
    pause: ok("pause"),
    resume: ok("resume"),
    cancel: ok("cancel"),
    retry: ok("retry") && opts.retryableFailures > 0,
    delete: opts.canDelete && canDeleteBroadcast(status),
  };
}

// ---------- Template oficial ----------

const KNOWN_KEYS = new Set<string>(TEMPLATE_VARIABLES.map((v) => v.key));

/** Lê MessageTemplate.providerVariables (Json) com segurança: só chaves conhecidas, na ordem */
export function parseProviderVariables(value: unknown): TemplateVariableKey[] {
  if (!Array.isArray(value)) return [];
  return value.filter((v): v is TemplateVariableKey => typeof v === "string" && KNOWN_KEYS.has(v)).slice(0, 20);
}

/**
 * Valores de {{1}}, {{2}}... do template aprovado, na ordem configurada.
 * A API da Meta rejeita parâmetros vazios, com quebras de linha/tabulação ou com muitos espaços seguidos.
 */
export function mapTemplateParameters(keys: unknown, ctx: TemplateContext): string[] {
  return parseProviderVariables(keys).map((k) => {
    const raw = String(ctx[k] ?? "")
      .replace(/[\r\n\t]+/g, " ")
      .replace(/ {2,}/g, " ")
      .trim();
    return raw || "-";
  });
}

// ---------- Mensagem de saída ----------

export interface TemplateForSend {
  type: string;
  mediaUrl: string | null;
  providerTemplateName: string | null;
  providerTemplateLanguage: string | null;
  providerVariables: unknown;
}

/** Mídia do modelo (somente URLs https; o provedor baixa o arquivo) */
export function mediaForTemplate(t: Pick<TemplateForSend, "type" | "mediaUrl">): OutgoingMessage["media"] | undefined {
  if (t.type !== "IMAGE" && t.type !== "DOCUMENT" && t.type !== "VIDEO") return undefined;
  if (!t.mediaUrl || !/^https:\/\//i.test(t.mediaUrl)) return undefined;
  const media: NonNullable<OutgoingMessage["media"]> = { type: t.type, url: t.mediaUrl };
  if (t.type === "DOCUMENT") {
    try {
      const name = decodeURIComponent(new URL(t.mediaUrl).pathname.split("/").pop() ?? "");
      if (name) media.filename = name.slice(0, 120);
    } catch {
      // URL inválida: sem nome de arquivo
    }
  }
  return media;
}

/** Monta a mensagem para o provedor a partir do texto já renderizado e do modelo */
export function buildOutgoingMessage(input: {
  to: string;
  renderedBody: string;
  template: TemplateForSend | null;
  requiresApprovedTemplate: boolean;
  context: TemplateContext;
}): OutgoingMessage {
  const msg: OutgoingMessage = { to: input.to, text: input.renderedBody };
  if (!input.template) return msg;
  const media = mediaForTemplate(input.template);
  if (media) msg.media = media;
  if (input.requiresApprovedTemplate && input.template.providerTemplateName) {
    msg.template = {
      name: input.template.providerTemplateName,
      language: input.template.providerTemplateLanguage || "pt_BR",
      parameters: mapTemplateParameters(input.template.providerVariables, input.context),
    };
  }
  return msg;
}

export type SendBlockerCode =
  | "connection_missing"
  | "connection_campaign"
  | "connection_status"
  | "provider_unknown"
  | "template_required";

/** Motivo para pausar em vez de enviar (conexão/provedor/modelo inadequados), ou null se está tudo certo */
export function sendBlocker(input: {
  connection: { status: string; campaignId: string } | null;
  campaignId: string;
  providerKnown: boolean;
  requiresApprovedTemplate: boolean;
  template: { providerTemplateName: string | null } | null;
}): { code: SendBlockerCode; message: string } | null {
  if (!input.connection) return { code: "connection_missing", message: "A conexão de WhatsApp do disparo foi excluída." };
  if (input.connection.campaignId !== input.campaignId) {
    return { code: "connection_campaign", message: "Conexão de WhatsApp inválida para esta campanha." };
  }
  if (input.connection.status !== "CONNECTED") {
    return { code: "connection_status", message: "A conexão de WhatsApp não está conectada." };
  }
  if (!input.providerKnown) return { code: "provider_unknown", message: "Provedor de WhatsApp desconhecido." };
  if (input.requiresApprovedTemplate && !input.template?.providerTemplateName) {
    return {
      code: "template_required",
      message: "A API oficial exige template aprovado e o modelo não tem o nome do template aprovado.",
    };
  }
  return null;
}

/** O eleitor ainda pode receber a mensagem? (consentimento pode ter sido retirado depois do agendamento) */
export function recipientSkipReason(
  voter: {
    campaignId: string;
    phone: string;
    whatsappOptIn: boolean;
    optOutAt: Date | null;
    consentAt: Date | null;
  } | null,
  message: { campaignId: string; phone: string },
): string | null {
  if (!voter) return "Eleitor excluído";
  if (voter.campaignId !== message.campaignId) return "Eleitor de outra campanha";
  if (voter.optOutAt) return "Eleitor pediu descadastro";
  if (!voter.whatsappOptIn || !voter.consentAt) return "Eleitor sem consentimento para WhatsApp";
  if (voter.phone !== message.phone) return "Telefone do eleitor foi alterado";
  return null;
}

/** Texto de erro seguro para gravar (limitado) */
export function truncateError(error: unknown, max = 500): string {
  const s = error instanceof Error ? error.message : typeof error === "string" ? error : "Erro desconhecido";
  return (s || "Erro desconhecido").slice(0, max);
}

/** Divide uma lista em blocos */
export function chunk<T>(list: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < list.length; i += size) out.push(list.slice(i, i + size));
  return out;
}
