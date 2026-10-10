// CONTRATO entre o módulo de provedores de WhatsApp e o módulo de disparos.
// Não altere as assinaturas sem atualizar os dois lados.
import type { WhatsAppProviderKey } from "@/lib/constants";

export type { WhatsAppProviderKey };

/** Mensagem a enviar para UM destinatário */
export interface OutgoingMessage {
  /** Telefone do destinatário só com dígitos, com DDI (ex.: 5511987654321) */
  to: string;
  /** Texto final já renderizado (usado em mensagens livres / legenda de mídia) */
  text: string;
  /** Mídia opcional (URL pública acessível pelo provedor) */
  media?: { type: "IMAGE" | "DOCUMENT" | "VIDEO"; url: string; filename?: string };
  /**
   * Template aprovado (API oficial da Meta / 360dialog). Mensagens iniciadas pela empresa fora da
   * janela de 24h EXIGEM template aprovado. parameters = valores de {{1}}, {{2}}... na ordem.
   */
  template?: { name: string; language: string; parameters: string[] };
}

export interface SendResult {
  ok: boolean;
  /** id da mensagem no provedor (usado para casar os webhooks de status) */
  providerMessageId?: string;
  error?: string;
  /** true quando vale tentar de novo (rate limit, erro 5xx, timeout) */
  retryable?: boolean;
}

export interface TestResult {
  ok: boolean;
  message: string;
  /** Número/nome verificado no provedor, quando disponível */
  phoneNumber?: string;
}

/** Evento normalizado recebido pelo webhook */
export type WebhookEvent =
  | {
      kind: "status";
      providerMessageId: string;
      status: "SENT" | "DELIVERED" | "READ" | "FAILED";
      error?: string;
      timestamp?: Date;
    }
  | {
      kind: "inbound";
      /** Telefone do remetente só com dígitos, com DDI */
      from: string;
      body: string;
      timestamp?: Date;
    };

/** Instância pronta para uso (credenciais já descriptografadas) */
export interface WhatsAppProvider {
  readonly key: WhatsAppProviderKey;
  send(message: OutgoingMessage): Promise<SendResult>;
  testConnection(): Promise<TestResult>;
}

export interface ProviderField {
  name: string;
  label: string;
  type: "text" | "password" | "url";
  required: boolean;
  placeholder?: string;
  help?: string;
  /** Campos secretos não são devolvidos ao navegador (exibidos mascarados) */
  secret?: boolean;
}

/** Requisição HTTP recebida no webhook, já lida */
export interface WebhookRequest {
  method: string;
  url: URL;
  headers: Headers;
  rawBody: string;
}

/** Resposta que o webhook deve devolver (ex.: challenge de verificação da Meta) */
export interface WebhookResponse {
  status: number;
  body: string;
  contentType?: string;
}

export interface ProviderDefinition {
  key: WhatsAppProviderKey;
  label: string;
  description: string;
  /** Provedor oficial/parceiro autorizado da Meta (exigência da Res. TSE 23.610/2019, art. 28, IV) */
  official: boolean;
  docsUrl?: string;
  /** Passo a passo exibido no assistente de configuração */
  setupSteps: string[];
  fields: ProviderField[];
  /** Exige template aprovado para iniciar conversas */
  requiresApprovedTemplate: boolean;
  create(credentials: Record<string, string>): WhatsAppProvider;
  /**
   * Trata GET de verificação (quando houver). Retorna null se a requisição não for de verificação.
   * webhookToken = WhatsAppConnection.webhookToken.
   */
  handleVerification?(req: WebhookRequest, credentials: Record<string, string>, webhookToken: string): WebhookResponse | null;
  /** Valida assinatura do webhook (quando o provedor oferece). Sem implementação = aceita. */
  verifySignature?(req: WebhookRequest, credentials: Record<string, string>): boolean;
  /** Converte o corpo do webhook em eventos normalizados */
  parseWebhook(req: WebhookRequest): WebhookEvent[];
}
