// Twilio — parceiro oficial da Meta (Business Solution Provider) para a WhatsApp Business Platform.
import { createHmac } from "node:crypto";
import { appUrl } from "@/lib/env";
import type {
  OutgoingMessage,
  ProviderDefinition,
  SendResult,
  TestResult,
  WebhookEvent,
  WebhookRequest,
  WhatsAppProvider,
} from "../types";
import { safeEqual } from "../cloud-api";
import { digitsOnly, isValidRecipient, providerRequest, sendFailureFromError, testFailureMessage, truncate } from "../http";

const TWILIO_API = "https://api.twilio.com/2010-04-01";

/** Erros comuns da Twilio (WhatsApp) em pt-BR */
const TWILIO_ERROR_MESSAGES: Record<number, string> = {
  20003: "Credenciais inválidas (Account SID ou Auth Token)",
  20404: "Recurso não encontrado na conta Twilio",
  20429: "Limite de requisições da Twilio atingido",
  21211: "Número de destino inválido",
  21606: "O número remetente não pertence a esta conta Twilio",
  21610: "O destinatário bloqueou mensagens deste remetente",
  21656: "Variáveis do template (ContentVariables) inválidas",
  30007: "Mensagem filtrada pela operadora/Meta",
  30008: "Erro desconhecido na entrega",
  63003: "O número de destino não usa WhatsApp",
  63007: "Remetente não habilitado para WhatsApp nesta conta Twilio",
  63016: "Fora da janela de 24h: use um template aprovado (Content SID HX…)",
  63018: "Limite de vazão do WhatsApp atingido",
  63024: "Destinatário inválido para mensagens de WhatsApp",
  63049: "A Meta não entregou esta mensagem de marketing para preservar a experiência do usuário",
};

const RETRYABLE_TWILIO_CODES = new Set([20429, 63018]);

export function describeTwilioError(code: number | string | null | undefined, message?: string | null): string {
  const n = typeof code === "string" ? Number(code) : code;
  const friendly = n !== undefined && n !== null && Number.isFinite(n) ? TWILIO_ERROR_MESSAGES[n] : undefined;
  const text = friendly ?? message ?? "Erro informado pela Twilio";
  return truncate(n !== undefined && n !== null && Number.isFinite(n) ? `${text} (código ${n})` : text, 500);
}

/** "+55 (11) 98765-4321" ou "whatsapp:+5511..." → "whatsapp:+5511987654321" */
export function twilioAddress(phone: string): string {
  return `whatsapp:+${digitsOnly(phone.replace(/^whatsapp:/i, ""))}`;
}

/** Parâmetros do POST /Messages.json */
export function buildTwilioParams(message: OutgoingMessage, creds: Record<string, string>): URLSearchParams {
  const params = new URLSearchParams();
  params.set("To", twilioAddress(message.to));
  params.set("From", twilioAddress(creds.fromNumber ?? ""));
  if (creds.messagingServiceSid) params.set("MessagingServiceSid", creds.messagingServiceSid);
  if (creds.statusCallbackUrl) params.set("StatusCallback", creds.statusCallbackUrl);

  const template = message.template;
  if (template && /^HX[0-9a-f]{32}$/i.test(template.name)) {
    // Template aprovado via Content API da Twilio: variáveis {{1}}, {{2}}...
    params.set("ContentSid", template.name);
    if (template.parameters.length) {
      const vars: Record<string, string> = {};
      template.parameters.forEach((p, i) => (vars[String(i + 1)] = p));
      params.set("ContentVariables", JSON.stringify(vars));
    }
  } else {
    if (message.text) params.set("Body", message.text);
    if (message.media) params.set("MediaUrl", message.media.url);
  }
  return params;
}

/** Assinatura X-Twilio-Signature: base64(HMAC-SHA1(authToken, url + chaves ordenadas + valores)) */
export function computeTwilioSignature(authToken: string, url: string, params: URLSearchParams | Record<string, string>): string {
  const entries: [string, string][] = params instanceof URLSearchParams ? Array.from(params.entries()) : Object.entries(params);
  const sorted = entries.sort(([ka, va], [kb, vb]) => (ka < kb ? -1 : ka > kb ? 1 : va < vb ? -1 : va > vb ? 1 : 0));
  const data = sorted.reduce((acc, [k, v]) => acc + k + v, url);
  return createHmac("sha1", authToken).update(data, "utf8").digest("base64");
}

/** URLs candidatas à assinatura: a pública (APP_URL, por causa de proxies) e a recebida, com/sem porta padrão */
export function twilioSignatureUrls(req: WebhookRequest, publicUrl: string): string[] {
  const urls = new Set<string>();
  for (const candidate of [publicUrl, req.url.href]) {
    urls.add(candidate);
    try {
      const u = new URL(candidate);
      urls.add(u.href); // new URL() remove a porta padrão
      if (!u.port) {
        // a Twilio pode ter assinado com a porta padrão explícita
        urls.add(`${u.protocol}//${u.hostname}:${u.protocol === "https:" ? 443 : 80}${u.pathname}${u.search}`);
      }
    } catch {
      // ignora URL inválida
    }
  }
  return Array.from(urls);
}

export function verifyTwilioSignature(req: WebhookRequest, authToken: string | undefined, publicUrl: string): boolean {
  const header = req.headers.get("x-twilio-signature");
  if (!authToken || !header) return false;
  const params = new URLSearchParams(req.rawBody);
  return twilioSignatureUrls(req, publicUrl).some((url) => safeEqual(header, computeTwilioSignature(authToken, url, params)));
}

const TWILIO_STATUS_MAP: Record<string, "SENT" | "DELIVERED" | "READ" | "FAILED"> = {
  sent: "SENT",
  delivered: "DELIVERED",
  read: "READ",
  failed: "FAILED",
  undelivered: "FAILED",
};

/** Webhooks da Twilio (form-encoded): callbacks de status e mensagens recebidas */
export function parseTwilioWebhookBody(rawBody: string): WebhookEvent[] {
  const p = new URLSearchParams(rawBody);
  const sid = p.get("MessageSid") ?? p.get("SmsSid");
  const messageStatus = (p.get("MessageStatus") ?? p.get("SmsStatus") ?? "").toLowerCase();

  if (messageStatus === "received" || (!p.get("MessageStatus") && p.has("Body"))) {
    const from = digitsOnly((p.get("WaId") || p.get("From") || "").replace(/^whatsapp:/i, ""));
    if (!from) return [];
    const body = p.get("Body") || p.get("ButtonText") || "";
    return [{ kind: "inbound", from, body }];
  }

  const status = TWILIO_STATUS_MAP[messageStatus];
  if (!sid || !status) return [];
  const event: WebhookEvent = { kind: "status", providerMessageId: sid, status };
  if (status === "FAILED") event.error = describeTwilioError(p.get("ErrorCode"), p.get("ErrorMessage"));
  return [event];
}

class TwilioProvider implements WhatsAppProvider {
  readonly key = "TWILIO" as const;
  constructor(private readonly creds: Record<string, string>) {}

  private authHeader(): string {
    return `Basic ${Buffer.from(`${this.creds.accountSid ?? ""}:${this.creds.authToken ?? ""}`).toString("base64")}`;
  }

  async send(message: OutgoingMessage): Promise<SendResult> {
    const { accountSid, authToken, fromNumber } = this.creds;
    if (!accountSid || !authToken || !fromNumber) return { ok: false, error: "Credenciais da Twilio incompletas", retryable: false };
    if (!isValidRecipient(message.to)) return { ok: false, error: "Número de destino inválido", retryable: false };
    try {
      const res = await providerRequest<{ sid?: string; code?: number; message?: string }>(
        `${TWILIO_API}/Accounts/${encodeURIComponent(accountSid)}/Messages.json`,
        {
          method: "POST",
          headers: { Authorization: this.authHeader(), "Content-Type": "application/x-www-form-urlencoded" },
          body: buildTwilioParams(message, this.creds).toString(),
        },
      );
      if (res.ok && res.data?.sid) return { ok: true, providerMessageId: res.data.sid };
      const code = res.data?.code;
      return {
        ok: false,
        error: describeTwilioError(code, res.data?.message ?? `Erro HTTP ${res.status} da Twilio`),
        retryable: res.status === 429 || res.status >= 500 || (code !== undefined && RETRYABLE_TWILIO_CODES.has(code)),
      };
    } catch (err) {
      return sendFailureFromError(err);
    }
  }

  async testConnection(): Promise<TestResult> {
    const { accountSid, authToken } = this.creds;
    if (!accountSid || !authToken) return { ok: false, message: "Informe o Account SID e o Auth Token." };
    try {
      const res = await providerRequest<{ friendly_name?: string; status?: string; code?: number; message?: string }>(
        `${TWILIO_API}/Accounts/${encodeURIComponent(accountSid)}.json`,
        { method: "GET", headers: { Authorization: this.authHeader() } },
      );
      if (!res.ok || !res.data) {
        return { ok: false, message: describeTwilioError(res.data?.code ?? (res.status === 401 ? 20003 : undefined), res.data?.message) };
      }
      if (res.data.status && res.data.status !== "active") {
        return { ok: false, message: `A conta Twilio está com status "${res.data.status}".` };
      }
      return {
        ok: true,
        message: `Conta Twilio ativa: ${res.data.friendly_name ?? accountSid}.`,
        phoneNumber: this.creds.fromNumber,
      };
    } catch (err) {
      return { ok: false, message: testFailureMessage(err) };
    }
  }
}

export const twilioProvider: ProviderDefinition = {
  key: "TWILIO",
  label: "Twilio",
  description:
    "Parceiro oficial da Meta (BSP), cobrança em cartão e API simples. Para iniciar conversas use templates aprovados (Content SID HX…).",
  official: true,
  docsUrl: "https://www.twilio.com/docs/whatsapp",
  setupSteps: [
    "No Console da Twilio, ative o WhatsApp (Messaging › Senders › WhatsApp senders) e registre o número da campanha pelo fluxo de cadastro da Meta.",
    "Copie o Account SID e o Auth Token da página inicial do Console.",
    "No remetente de WhatsApp, em \"Webhook URL for incoming messages\", cole a URL de callback abaixo (método POST).",
    "Os status de entrega e leitura são configurados automaticamente em cada envio (StatusCallback).",
    "Crie os templates em Messaging › Content Template Builder, envie para aprovação do WhatsApp e use o Content SID (HX…) nos modelos de mensagem.",
  ],
  fields: [
    {
      name: "accountSid",
      label: "Account SID",
      type: "text",
      required: true,
      placeholder: "AC…",
      help: "Começa com AC e tem 34 caracteres.",
    },
    {
      name: "authToken",
      label: "Auth Token",
      type: "password",
      required: true,
      secret: true,
      help: "Também usado para validar a assinatura dos webhooks.",
    },
    {
      name: "fromNumber",
      label: "Número remetente do WhatsApp",
      type: "text",
      required: true,
      placeholder: "+5511999999999",
      help: "Número habilitado como remetente de WhatsApp na Twilio, no formato internacional.",
    },
    {
      name: "messagingServiceSid",
      label: "Messaging Service SID",
      type: "text",
      required: false,
      placeholder: "MG…",
      help: "Opcional. Use se o remetente estiver em um Messaging Service.",
    },
  ],
  requiresApprovedTemplate: true,
  create: (credentials) => new TwilioProvider(credentials),
  verifySignature: (req, credentials) =>
    verifyTwilioSignature(req, credentials.authToken, appUrl(`${req.url.pathname}${req.url.search}`)),
  parseWebhook: (req) => parseTwilioWebhookBody(req.rawBody),
};
