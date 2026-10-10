// Formato da WhatsApp Cloud API (Meta), compartilhado pela Meta e pela 360dialog:
// montagem do corpo de envio, leitura de respostas/erros, webhooks, verificação e assinatura.
// Funções puras (sem banco, sem rede).
import { createHmac, timingSafeEqual } from "node:crypto";
import type { OutgoingMessage, SendResult, WebhookEvent, WebhookRequest, WebhookResponse } from "./types";
import { digitsOnly, truncate, unixToDate } from "./http";

export const DEFAULT_GRAPH_API_VERSION = "v21.0";

/** Códigos de erro da Meta que indicam limite de taxa/vazão (vale tentar de novo mais tarde) */
export const RETRYABLE_CLOUD_ERROR_CODES = new Set([1, 2, 4, 130429, 131048, 131056, 80007]);

/** Mensagens amigáveis para os erros mais comuns da Cloud API */
const CLOUD_ERROR_MESSAGES: Record<number, string> = {
  0: "Falha de autenticação na API da Meta",
  4: "Limite de chamadas do app atingido",
  100: "Parâmetro inválido na requisição",
  190: "Token de acesso inválido ou expirado",
  200: "Permissão insuficiente no token de acesso",
  368: "Conta temporariamente bloqueada por violação de políticas",
  130429: "Limite de vazão da API atingido",
  130472: "Número do destinatário faz parte de um experimento da Meta (mensagem não entregue)",
  131026: "Mensagem não entregável (o número não usa WhatsApp ou não aceitou os termos)",
  131030: "Número do destinatário não está na lista de números de teste permitidos",
  131031: "Conta do WhatsApp Business bloqueada ou restrita",
  131042: "Problema de pagamento na conta do WhatsApp Business",
  131047: "Mais de 24h desde a última mensagem do contato: é preciso usar um template aprovado",
  131048: "Limite de envio atingido por denúncias de spam (qualidade do número)",
  131049: "A Meta não entregou esta mensagem de marketing para preservar a experiência do usuário",
  131050: "O destinatário optou por não receber mensagens de marketing",
  131051: "Tipo de mensagem não suportado",
  131053: "Falha ao enviar a mídia (verifique se a URL é pública)",
  131056: "Muitas mensagens para o mesmo destinatário em pouco tempo",
  132000: "Quantidade de parâmetros não confere com o template aprovado",
  132001: "Template inexistente ou não aprovado neste idioma",
  132005: "Texto do template ficou longo demais após preencher os parâmetros",
  132007: "O conteúdo viola a política de formatação do template",
  132012: "Formato dos parâmetros não confere com o template aprovado",
  132015: "Template pausado por baixa qualidade",
  132016: "Template desativado por baixa qualidade",
  133010: "Número de telefone não registrado na Cloud API",
  80007: "Limite de taxa da conta do WhatsApp Business atingido",
};

interface CloudErrorObject {
  message?: string;
  title?: string;
  code?: number | string;
  error_data?: { details?: string };
  details?: string;
}

/** Descreve um erro da Cloud API em pt-BR (mensagem amigável quando conhecida + código) */
export function describeCloudError(err: CloudErrorObject | null | undefined): string | null {
  if (!err) return null;
  const code = typeof err.code === "string" ? Number(err.code) : err.code;
  const friendly = code !== undefined && Number.isFinite(code) ? CLOUD_ERROR_MESSAGES[code] : undefined;
  const raw = friendly ?? err.title ?? err.error_data?.details ?? err.details ?? err.message;
  if (!raw) return code !== undefined ? `Erro ${code} do provedor` : null;
  return truncate(code !== undefined && Number.isFinite(code) ? `${raw} (código ${code})` : raw, 500);
}

/** Parâmetros de template não aceitam quebras de linha, tabs nem mais de 4 espaços seguidos */
export function sanitizeTemplateParam(value: string): string {
  const v = (value ?? "").replace(/[\r\n\t]+/g, " ").replace(/ {4,}/g, "   ").trim();
  return v || "-";
}

type CloudMediaKind = "image" | "document" | "video";

function mediaKind(type: "IMAGE" | "DOCUMENT" | "VIDEO"): CloudMediaKind {
  return type === "IMAGE" ? "image" : type === "VIDEO" ? "video" : "document";
}

/** Corpo JSON de POST /{phone-number-id}/messages (Cloud API) */
export function buildCloudApiPayload(message: OutgoingMessage): Record<string, unknown> {
  const base = { messaging_product: "whatsapp", recipient_type: "individual", to: digitsOnly(message.to) };

  if (message.template) {
    const components: Record<string, unknown>[] = [];
    if (message.media) {
      const kind = mediaKind(message.media.type);
      const media: Record<string, string> = { link: message.media.url };
      if (kind === "document" && message.media.filename) media.filename = message.media.filename;
      components.push({ type: "header", parameters: [{ type: kind, [kind]: media }] });
    }
    if (message.template.parameters.length) {
      components.push({
        type: "body",
        parameters: message.template.parameters.map((p) => ({ type: "text", text: sanitizeTemplateParam(p) })),
      });
    }
    return {
      ...base,
      type: "template",
      template: {
        name: message.template.name,
        language: { code: message.template.language },
        ...(components.length ? { components } : {}),
      },
    };
  }

  if (message.media) {
    const kind = mediaKind(message.media.type);
    const media: Record<string, string> = { link: message.media.url };
    if (message.text.trim()) media.caption = message.text;
    if (kind === "document" && message.media.filename) media.filename = message.media.filename;
    return { ...base, type: kind, [kind]: media };
  }

  return { ...base, type: "text", text: { body: message.text, preview_url: true } };
}

interface CloudSendResponse {
  messages?: { id?: string }[];
  error?: CloudErrorObject;
  /** Formato antigo da 360dialog (v1) */
  errors?: CloudErrorObject[];
  meta?: { developer_message?: string; http_code?: number };
}

/** Interpreta a resposta do envio (Cloud API / 360dialog) */
export function parseCloudApiSendResponse(status: number, data: unknown): SendResult {
  const body = (data && typeof data === "object" ? data : {}) as CloudSendResponse;
  const id = body.messages?.[0]?.id;
  if (status >= 200 && status < 300 && id) return { ok: true, providerMessageId: id };

  const errObj = body.error ?? body.errors?.[0];
  const rawCode = errObj?.code;
  const code = typeof rawCode === "string" ? Number(rawCode) : rawCode;
  const error =
    describeCloudError(errObj) ??
    (body.meta?.developer_message ? truncate(body.meta.developer_message, 500) : null) ??
    (status >= 200 && status < 300 ? "Resposta do provedor sem id da mensagem" : `Erro HTTP ${status} do provedor`);
  const retryable = status === 429 || status >= 500 || (code !== undefined && RETRYABLE_CLOUD_ERROR_CODES.has(code));
  return { ok: false, error, retryable };
}

const QUALITY_LABELS: Record<string, string> = {
  GREEN: "alta",
  YELLOW: "média",
  RED: "baixa",
  UNKNOWN: "ainda não avaliada",
};

export function qualityLabel(rating: string | undefined | null): string | null {
  if (!rating) return null;
  return QUALITY_LABELS[rating.toUpperCase()] ?? rating.toLowerCase();
}

// ---------------- Webhooks ----------------

const STATUS_MAP: Record<string, "SENT" | "DELIVERED" | "READ" | "FAILED"> = {
  sent: "SENT",
  delivered: "DELIVERED",
  read: "READ",
  failed: "FAILED",
};

const MEDIA_LABELS: Record<string, string> = {
  image: "[imagem]",
  audio: "[áudio]",
  voice: "[áudio]",
  video: "[vídeo]",
  document: "[documento]",
  sticker: "[figurinha]",
  location: "[localização]",
  contacts: "[contato]",
  reaction: "[reação]",
  unsupported: "[mensagem não suportada]",
};

interface CloudInboundMessage {
  from?: string;
  timestamp?: string;
  type?: string;
  text?: { body?: string };
  button?: { text?: string; payload?: string };
  interactive?: { button_reply?: { title?: string }; list_reply?: { title?: string } };
  image?: { caption?: string };
  video?: { caption?: string };
  document?: { caption?: string };
  reaction?: { emoji?: string };
}

interface CloudStatus {
  id?: string;
  status?: string;
  timestamp?: string;
  errors?: CloudErrorObject[];
}

interface CloudValue {
  statuses?: CloudStatus[];
  messages?: CloudInboundMessage[];
}

function inboundBody(m: CloudInboundMessage): string {
  const body =
    m.text?.body ??
    m.button?.text ??
    m.interactive?.button_reply?.title ??
    m.interactive?.list_reply?.title ??
    m.image?.caption ??
    m.video?.caption ??
    m.document?.caption ??
    m.reaction?.emoji;
  if (body) return body;
  return MEDIA_LABELS[m.type ?? ""] ?? (m.type ? `[${m.type}]` : "");
}

function eventsFromValue(value: CloudValue, out: WebhookEvent[]) {
  for (const s of Array.isArray(value.statuses) ? value.statuses : []) {
    const status = s?.status ? STATUS_MAP[s.status] : undefined;
    if (!s?.id || !status) continue;
    const event: WebhookEvent = { kind: "status", providerMessageId: String(s.id), status, timestamp: unixToDate(s.timestamp) };
    if (status === "FAILED") event.error = describeCloudError(s.errors?.[0]) ?? "Falha na entrega informada pela Meta";
    out.push(event);
  }
  for (const m of Array.isArray(value.messages) ? value.messages : []) {
    const from = digitsOnly(m?.from);
    if (!from) continue;
    out.push({ kind: "inbound", from, body: inboundBody(m), timestamp: unixToDate(m.timestamp) });
  }
}

/**
 * Converte o corpo de um webhook da Cloud API em eventos normalizados.
 * Formato: { object, entry: [{ changes: [{ value: { statuses: [...], messages: [...] } }] }] }.
 * Também aceita o formato "achatado" (statuses/messages na raiz) da 360dialog v1.
 */
export function parseCloudApiWebhookBody(rawBody: string): WebhookEvent[] {
  let payload: unknown;
  try {
    payload = JSON.parse(rawBody);
  } catch {
    return [];
  }
  if (!payload || typeof payload !== "object") return [];
  const out: WebhookEvent[] = [];
  const root = payload as { entry?: { changes?: { value?: CloudValue }[] }[] } & CloudValue;
  for (const entry of Array.isArray(root.entry) ? root.entry : []) {
    for (const change of Array.isArray(entry?.changes) ? entry.changes : []) {
      if (change?.value && typeof change.value === "object") eventsFromValue(change.value, out);
    }
  }
  if (!Array.isArray(root.entry) && (root.statuses || root.messages)) eventsFromValue(root, out);
  return out;
}

/** Comparação de strings em tempo constante */
export function safeEqual(a: string, b: string): boolean {
  const ab = Buffer.from(a, "utf8");
  const bb = Buffer.from(b, "utf8");
  if (ab.length !== bb.length) return false;
  return timingSafeEqual(ab, bb);
}

const CHALLENGE_RE = /^[A-Za-z0-9_.-]{1,512}$/;

/**
 * Handshake de verificação da Meta: GET ?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...
 * Retorna null quando a requisição não é de verificação.
 */
export function handleCloudVerification(req: WebhookRequest, webhookToken: string): WebhookResponse | null {
  if (req.method.toUpperCase() !== "GET") return null;
  const mode = req.url.searchParams.get("hub.mode");
  if (!mode) return null;
  const token = req.url.searchParams.get("hub.verify_token") ?? "";
  const challenge = req.url.searchParams.get("hub.challenge") ?? "";
  if (mode !== "subscribe" || !webhookToken || !safeEqual(token, webhookToken)) {
    return { status: 403, body: "Forbidden", contentType: "text/plain; charset=utf-8" };
  }
  if (!CHALLENGE_RE.test(challenge)) return { status: 400, body: "Bad request", contentType: "text/plain; charset=utf-8" };
  return { status: 200, body: challenge, contentType: "text/plain; charset=utf-8" };
}

export function computeCloudSignature(appSecret: string, rawBody: string): string {
  return `sha256=${createHmac("sha256", appSecret).update(rawBody, "utf8").digest("hex")}`;
}

/** Valida X-Hub-Signature-256. Sem App Secret configurado, aceita (a URL secreta já autentica). */
export function verifyCloudSignature(rawBody: string, header: string | null, appSecret: string | undefined): boolean {
  if (!appSecret) return true;
  if (!header || !header.toLowerCase().startsWith("sha256=")) return false;
  const received = `sha256=${header.slice(7).trim().toLowerCase()}`;
  return safeEqual(received, computeCloudSignature(appSecret, rawBody));
}
