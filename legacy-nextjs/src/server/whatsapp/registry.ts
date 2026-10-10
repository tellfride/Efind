// Registro dos provedores de WhatsApp. Contrato usado pelo módulo de disparos (e pelo worker):
// mantenha as assinaturas de PROVIDERS, getProviderDefinition, providerForConnection e getDefaultConnection.
// Puro Node + Prisma (sem next/*).
import type { WhatsAppConnection } from "@prisma/client";
import { prisma } from "@/lib/db";
import { decryptJson } from "@/lib/crypto";
import { appUrl } from "@/lib/env";
import type { WhatsAppProviderKey } from "@/lib/constants";
import type { ProviderDefinition, WhatsAppProvider } from "./types";
import { sanitizeCredentialObject } from "./credentials";
import { metaCloudProvider } from "./providers/meta-cloud";
import { dialog360Provider } from "./providers/dialog360";
import { twilioProvider } from "./providers/twilio";
import { sandboxProvider } from "./providers/sandbox";

/** Todos os provedores disponíveis (ordem de exibição). Apenas API oficial, parceiros oficiais e simulador. */
export const PROVIDERS: ProviderDefinition[] = [metaCloudProvider, dialog360Provider, twilioProvider, sandboxProvider];

export function getProviderDefinition(key: WhatsAppProviderKey | string): ProviderDefinition | null {
  return PROVIDERS.find((p) => p.key === key) ?? null;
}

/** URL pública do webhook de uma conexão */
export function webhookUrlFor(webhookToken: string): string {
  return appUrl(`/api/webhooks/whatsapp/${webhookToken}`);
}

/** Descriptografa as credenciais salvas (lança erro se a chave de criptografia não confere) */
export function decryptCredentials(encrypted: string): Record<string, string> {
  return sanitizeCredentialObject(decryptJson<unknown>(encrypted));
}

/**
 * Descriptografa as credenciais da conexão e cria a instância do provedor.
 * Injeta statusCallbackUrl (Twilio) e __connectionId/__campaignId (simulador).
 */
export function providerForConnection(
  connection: Pick<WhatsAppConnection, "provider" | "credentials"> &
    Partial<Pick<WhatsAppConnection, "id" | "campaignId" | "webhookToken">>,
): WhatsAppProvider {
  const definition = getProviderDefinition(connection.provider);
  if (!definition) throw new Error(`Provedor de WhatsApp desconhecido: ${connection.provider}`);
  const credentials = decryptCredentials(connection.credentials);
  if (connection.webhookToken) credentials.statusCallbackUrl = webhookUrlFor(connection.webhookToken);
  if (connection.id) credentials.__connectionId = connection.id;
  if (connection.campaignId) credentials.__campaignId = connection.campaignId;
  return definition.create(credentials);
}

/** Conexão padrão ativa (status CONNECTED) da campanha; senão a primeira conectada; senão null */
export async function getDefaultConnection(campaignId: string): Promise<WhatsAppConnection | null> {
  const preferred = await prisma.whatsAppConnection.findFirst({
    where: { campaignId, isDefault: true, status: "CONNECTED" },
  });
  if (preferred) return preferred;
  return prisma.whatsAppConnection.findFirst({
    where: { campaignId, status: "CONNECTED" },
    orderBy: { createdAt: "asc" },
  });
}
