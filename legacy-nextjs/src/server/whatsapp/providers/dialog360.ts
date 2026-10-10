// 360dialog — parceiro oficial da Meta (Business Solution Provider). Usa o formato da Cloud API.
import type { OutgoingMessage, ProviderDefinition, SendResult, TestResult, WhatsAppProvider } from "../types";
import { buildCloudApiPayload, parseCloudApiSendResponse, parseCloudApiWebhookBody } from "../cloud-api";
import { isValidRecipient, providerRequest, sendFailureFromError, testFailureMessage } from "../http";

export const DIALOG360_DEFAULT_BASE_URL = "https://waba-v2.360dialog.io";

export function dialog360BaseUrl(creds: Record<string, string>): string {
  return ((creds.baseUrl ?? "").trim() || DIALOG360_DEFAULT_BASE_URL).replace(/\/+$/, "");
}

function headers(creds: Record<string, string>, json = false): HeadersInit {
  return { "D360-API-KEY": creds.apiKey ?? "", ...(json ? { "Content-Type": "application/json" } : {}) };
}

function errorMessage(status: number, data: unknown): string {
  const d = (data && typeof data === "object" ? data : {}) as {
    error?: { message?: string };
    meta?: { developer_message?: string };
    errors?: { title?: string; details?: string }[];
  };
  if (status === 401 || status === 403) return "Chave de API (D360-API-KEY) inválida ou sem permissão.";
  return (
    d.error?.message ?? d.meta?.developer_message ?? d.errors?.[0]?.details ?? d.errors?.[0]?.title ?? `A 360dialog respondeu com erro HTTP ${status}.`
  );
}

class Dialog360Provider implements WhatsAppProvider {
  readonly key = "DIALOG360" as const;
  constructor(private readonly creds: Record<string, string>) {}

  async send(message: OutgoingMessage): Promise<SendResult> {
    if (!this.creds.apiKey) return { ok: false, error: "Chave de API da 360dialog não configurada", retryable: false };
    if (!isValidRecipient(message.to)) return { ok: false, error: "Número de destino inválido", retryable: false };
    try {
      const res = await providerRequest(`${dialog360BaseUrl(this.creds)}/messages`, {
        method: "POST",
        headers: headers(this.creds, true),
        body: JSON.stringify(buildCloudApiPayload(message)),
      });
      return parseCloudApiSendResponse(res.status, res.data);
    } catch (err) {
      return sendFailureFromError(err);
    }
  }

  async testConnection(): Promise<TestResult> {
    if (!this.creds.apiKey) return { ok: false, message: "Informe a chave de API da 360dialog." };
    try {
      const res = await providerRequest<{ url?: string }>(`${dialog360BaseUrl(this.creds)}/v1/configs/webhook`, {
        method: "GET",
        headers: headers(this.creds),
      });
      if (!res.ok) return { ok: false, message: errorMessage(res.status, res.data) };
      const url = res.data?.url;
      return {
        ok: true,
        message: url ? "Chave de API válida. Webhook configurado na 360dialog." : "Chave de API válida. Nenhum webhook registrado ainda.",
      };
    } catch (err) {
      return { ok: false, message: testFailureMessage(err) };
    }
  }
}

/** Registra a URL de webhook do E-Find na 360dialog (POST /v1/configs/webhook) */
export async function registerDialog360Webhook(
  creds: Record<string, string>,
  url: string,
): Promise<{ ok: boolean; message: string }> {
  if (!creds.apiKey) return { ok: false, message: "Chave de API da 360dialog não configurada." };
  try {
    const res = await providerRequest(`${dialog360BaseUrl(creds)}/v1/configs/webhook`, {
      method: "POST",
      headers: headers(creds, true),
      body: JSON.stringify({ url }),
    });
    if (!res.ok) return { ok: false, message: errorMessage(res.status, res.data) };
    return { ok: true, message: "Webhook registrado na 360dialog." };
  } catch (err) {
    return { ok: false, message: testFailureMessage(err) };
  }
}

export const dialog360Provider: ProviderDefinition = {
  key: "DIALOG360",
  label: "360dialog",
  description:
    "Parceiro oficial da Meta (BSP) com painel próprio e suporte em português. Mesmo formato da Cloud API; exige templates aprovados.",
  official: true,
  docsUrl: "https://docs.360dialog.com/docs/waba-messaging/messaging",
  setupSteps: [
    "Crie sua conta no 360dialog Hub (hub.360dialog.com) e conecte o número da campanha à WhatsApp Business Platform.",
    "No Hub, gere a chave de API (D360-API-KEY) do número e cole abaixo.",
    "Registre o webhook: use o botão \"Registrar webhook automaticamente\" ou configure a URL de callback abaixo pela API da 360dialog.",
    "Crie os templates de mensagem no Hub e aguarde a aprovação da Meta antes de disparar.",
  ],
  fields: [
    {
      name: "apiKey",
      label: "Chave de API (D360-API-KEY)",
      type: "password",
      required: true,
      secret: true,
      help: "Gerada no 360dialog Hub para o número conectado.",
    },
    {
      name: "baseUrl",
      label: "URL base da API",
      type: "url",
      required: false,
      placeholder: DIALOG360_DEFAULT_BASE_URL,
      help: "Deixe em branco para usar a API de produção (v2).",
    },
  ],
  requiresApprovedTemplate: true,
  create: (credentials) => new Dialog360Provider(credentials),
  parseWebhook: (req) => parseCloudApiWebhookBody(req.rawBody),
};
