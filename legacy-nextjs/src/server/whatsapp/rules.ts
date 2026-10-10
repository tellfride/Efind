// Regras puras do webhook: progressão de status das mensagens, descadastro ("SAIR") e
// normalização de telefones recebidos. Sem banco e sem rede (testável).
import { OPT_OUT_KEYWORDS, type MessageStatus } from "@/lib/constants";
import { normalizeBrPhone } from "@/lib/phone";

export type WebhookStatus = "SENT" | "DELIVERED" | "READ" | "FAILED";

const PROGRESS: Record<string, number> = { PENDING: 0, SENDING: 1, SENT: 2, DELIVERED: 3, READ: 4 };

/** Ordem de aplicação dos eventos de um mesmo lote */
export function statusRank(status: WebhookStatus): number {
  return status === "FAILED" ? 5 : PROGRESS[status];
}

/**
 * Próximo status de uma BroadcastMessage diante de um evento do provedor, ou null se nada muda.
 * - O status só avança: SENT < DELIVERED < READ (eventos atrasados/duplicados são ignorados).
 * - FAILED só vale se a mensagem ainda não foi entregue/lida.
 * - Entrega/leitura confirmadas prevalecem sobre uma falha anterior.
 * - SKIPPED (não enviada) nunca muda.
 */
export function nextMessageStatus(current: string, incoming: WebhookStatus): MessageStatus | null {
  if (current === "SKIPPED") return null;
  if (incoming === "FAILED") {
    return current === "DELIVERED" || current === "READ" || current === "FAILED" ? null : "FAILED";
  }
  if (current === "FAILED") return incoming === "SENT" ? null : incoming;
  const cur = PROGRESS[current] ?? -1;
  return PROGRESS[incoming] > cur ? incoming : null;
}

export interface StatusRow {
  status: string;
  sentAt: Date | null;
  deliveredAt: Date | null;
  readAt: Date | null;
}

export interface StatusUpdate {
  status: MessageStatus;
  sentAt?: Date;
  deliveredAt?: Date;
  readAt?: Date;
  error?: string | null;
}

/** Dados de atualização da mensagem para um evento de status (null = ignorar) */
export function buildStatusUpdate(
  row: StatusRow,
  event: { status: WebhookStatus; error?: string; timestamp?: Date },
  now: Date = new Date(),
): StatusUpdate | null {
  const next = nextMessageStatus(row.status, event.status);
  if (!next) return null;
  const at = event.timestamp ?? now;
  const data: StatusUpdate = { status: next };
  if (next === "FAILED") {
    data.error = (event.error ?? "Falha na entrega informada pelo provedor").slice(0, 500);
    return data;
  }
  if (!row.sentAt) data.sentAt = at;
  if (next === "DELIVERED" || next === "READ") {
    if (!row.deliveredAt) data.deliveredAt = at;
  }
  if (next === "READ" && !row.readAt) data.readAt = at;
  if (row.status === "FAILED") data.error = null;
  return data;
}

// Botões de descadastro dos templates de marketing da Meta
const EXTRA_OPT_OUT_PHRASES = ["PARAR PROMOCOES", "STOP PROMOTIONS"];
const OPT_OUT_SET = new Set<string>([...OPT_OUT_KEYWORDS, ...EXTRA_OPT_OUT_PHRASES]);

/** Normaliza o texto recebido: sem acentos, caixa alta, sem pontuação/emojis, espaços únicos */
export function normalizeOptOutText(body: string | null | undefined): string {
  return (body ?? "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toUpperCase()
    .replace(/[^A-Z0-9\s]+/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/** A mensagem é um pedido de descadastro? (texto igual a uma das palavras-chave) */
export function isOptOutMessage(body: string | null | undefined): boolean {
  const normalized = normalizeOptOutText(body);
  return normalized !== "" && OPT_OUT_SET.has(normalized);
}

/**
 * Telefones possíveis para casar o remetente com o eleitor cadastrado.
 * O WhatsApp informa muitos celulares brasileiros antigos SEM o nono dígito (55 + DDD + 8 dígitos),
 * enquanto o cadastro guarda 55 + DDD + 9 dígitos — testamos as duas formas.
 */
export function inboundPhoneCandidates(raw: string | null | undefined): string[] {
  const digits = (raw ?? "").replace(/\D/g, "");
  if (!digits) return [];
  const out = new Set<string>([digits]);
  const normalized = normalizeBrPhone(digits);
  if (normalized) out.add(normalized);
  const base = normalized ?? digits;
  if (base.startsWith("55")) {
    const local = base.slice(2);
    if (local.length === 10 && /[6-9]/.test(local[2])) out.add(`55${local.slice(0, 2)}9${local.slice(2)}`);
    if (local.length === 11 && local[2] === "9") out.add(`55${local.slice(0, 2)}${local.slice(3)}`);
  }
  return Array.from(out);
}

/** Forma canônica para guardar o remetente: celular brasileiro com nono dígito; senão, só dígitos */
export function canonicalInboundPhone(raw: string | null | undefined): string {
  const digits = (raw ?? "").replace(/\D/g, "");
  const normalized = normalizeBrPhone(digits);
  if (normalized) {
    const local = normalized.slice(2);
    if (local.length === 10 && /[6-9]/.test(local[2])) return `55${local.slice(0, 2)}9${local.slice(2)}`;
    return normalized;
  }
  return digits;
}
