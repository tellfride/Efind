// WhatsApp Cloud API — API oficial da Meta (WhatsApp Business Platform).
import type { OutgoingMessage, ProviderDefinition, SendResult, TestResult, WhatsAppProvider } from "../types";
import {
  DEFAULT_GRAPH_API_VERSION,
  buildCloudApiPayload,
  describeCloudError,
  handleCloudVerification,
  parseCloudApiSendResponse,
  parseCloudApiWebhookBody,
  qualityLabel,
  verifyCloudSignature,
} from "../cloud-api";
import { isValidRecipient, providerRequest, sendFailureFromError, testFailureMessage } from "../http";

export function graphBaseUrl(apiVersion: string | undefined): string {
  const version = (apiVersion ?? "").trim() || DEFAULT_GRAPH_API_VERSION;
  return `https://graph.facebook.com/${encodeURIComponent(version)}`;
}

class MetaCloudProvider implements WhatsAppProvider {
  readonly key = "META_CLOUD" as const;
  constructor(private readonly creds: Record<string, string>) {}

  private headers(json = false): HeadersInit {
    return {
      Authorization: `Bearer ${this.creds.accessToken ?? ""}`,
      ...(json ? { "Content-Type": "application/json" } : {}),
    };
  }

  async send(message: OutgoingMessage): Promise<SendResult> {
    if (!this.creds.phoneNumberId || !this.creds.accessToken) {
      return { ok: false, error: "Credenciais da Meta incompletas", retryable: false };
    }
    if (!isValidRecipient(message.to)) return { ok: false, error: "Número de destino inválido", retryable: false };
    try {
      const res = await providerRequest(
        `${graphBaseUrl(this.creds.apiVersion)}/${encodeURIComponent(this.creds.phoneNumberId)}/messages`,
        { method: "POST", headers: this.headers(true), body: JSON.stringify(buildCloudApiPayload(message)) },
      );
      return parseCloudApiSendResponse(res.status, res.data);
    } catch (err) {
      return sendFailureFromError(err);
    }
  }

  async testConnection(): Promise<TestResult> {
    if (!this.creds.phoneNumberId || !this.creds.accessToken) {
      return { ok: false, message: "Informe o ID do número e o token de acesso." };
    }
    try {
      const res = await providerRequest<{
        display_phone_number?: string;
        verified_name?: string;
        quality_rating?: string;
        error?: { message?: string; code?: number };
      }>(
        `${graphBaseUrl(this.creds.apiVersion)}/${encodeURIComponent(this.creds.phoneNumberId)}?fields=display_phone_number,verified_name,quality_rating`,
        { method: "GET", headers: this.headers() },
      );
      if (!res.ok || !res.data || res.data.error) {
        return {
          ok: false,
          message: describeCloudError(res.data?.error) ?? `A Meta respondeu com erro HTTP ${res.status}.`,
        };
      }
      const { display_phone_number: phone, verified_name: name, quality_rating: rating } = res.data;
      const parts = [`Conectado à Meta: ${name ?? "número verificado"}${phone ? ` (${phone})` : ""}`];
      const quality = qualityLabel(rating);
      if (quality) parts.push(`qualidade ${quality}`);
      return { ok: true, message: `${parts.join(" · ")}.`, phoneNumber: phone };
    } catch (err) {
      return { ok: false, message: testFailureMessage(err) };
    }
  }
}

export const metaCloudProvider: ProviderDefinition = {
  key: "META_CLOUD",
  label: "WhatsApp Cloud API (Meta)",
  description:
    "API oficial do WhatsApp Business, hospedada pela própria Meta. Melhor custo e entregabilidade; exige app no Meta for Developers e templates aprovados.",
  official: true,
  docsUrl: "https://developers.facebook.com/docs/whatsapp/cloud-api/get-started",
  setupSteps: [
    "No Meta for Developers (developers.facebook.com), crie um app do tipo Empresa e adicione o produto WhatsApp.",
    "Em WhatsApp › Configuração da API, adicione e verifique o número de telefone da campanha. Copie o ID do número de telefone e o ID da conta do WhatsApp Business.",
    "No Gerenciador de Negócios, crie um Usuário do Sistema, atribua o app e a conta do WhatsApp e gere um token permanente com as permissões whatsapp_business_messaging e whatsapp_business_management.",
    "Em WhatsApp › Configuração, configure o webhook: cole a URL de callback e o token de verificação abaixo e assine o campo \"messages\".",
    "Copie a Chave secreta do app (Configurações do app › Básico) para validar a assinatura dos webhooks.",
    "No WhatsApp Manager, crie os templates de mensagem e aguarde a aprovação da Meta antes de disparar.",
  ],
  fields: [
    {
      name: "phoneNumberId",
      label: "ID do número de telefone",
      type: "text",
      required: true,
      placeholder: "123456789012345",
      help: "Phone number ID, em WhatsApp › Configuração da API.",
    },
    {
      name: "businessAccountId",
      label: "ID da conta do WhatsApp Business (WABA)",
      type: "text",
      required: false,
      placeholder: "109876543210987",
      help: "Opcional. Ajuda a identificar a conta no Gerenciador de Negócios.",
    },
    {
      name: "accessToken",
      label: "Token de acesso permanente",
      type: "password",
      required: true,
      secret: true,
      placeholder: "EAAG…",
      help: "Token de Usuário do Sistema com whatsapp_business_messaging e whatsapp_business_management.",
    },
    {
      name: "appSecret",
      label: "Chave secreta do app (App Secret)",
      type: "password",
      required: false,
      secret: true,
      help: "Recomendado: valida a assinatura X-Hub-Signature-256 de cada webhook.",
    },
    {
      name: "apiVersion",
      label: "Versão da Graph API",
      type: "text",
      required: false,
      placeholder: DEFAULT_GRAPH_API_VERSION,
      help: `Deixe em branco para usar ${DEFAULT_GRAPH_API_VERSION}.`,
    },
  ],
  requiresApprovedTemplate: true,
  create: (credentials) => new MetaCloudProvider(credentials),
  handleVerification: (req, _credentials, webhookToken) => handleCloudVerification(req, webhookToken),
  verifySignature: (req, credentials) =>
    verifyCloudSignature(req.rawBody, req.headers.get("x-hub-signature-256"), credentials.appSecret),
  parseWebhook: (req) => parseCloudApiWebhookBody(req.rawBody),
};
