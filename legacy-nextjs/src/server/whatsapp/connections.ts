// Operações de conexão usadas pela interface (/painel/whatsapp) e pelas Server Actions.
// Sem next/*: apenas Prisma + registro de provedores.
import type { WhatsAppConnection } from "@prisma/client";
import { prisma } from "@/lib/db";
import type { ConnectionStatus, WhatsAppProviderKey } from "@/lib/constants";
import type { TestResult } from "./types";
import { decryptCredentials, getProviderDefinition, providerForConnection, webhookUrlFor } from "./registry";
import { splitCredentials } from "./credentials";

/** Disparos que impedem excluir a conexão */
export const ACTIVE_BROADCAST_STATUSES = ["RUNNING", "SCHEDULED", "PAUSED"] as const;

/** Conexão para o assistente de configuração/edição (segredos mascarados) */
export interface ConnectionView {
  id: string;
  name: string;
  provider: WhatsAppProviderKey;
  status: ConnectionStatus;
  phoneNumber: string | null;
  isDefault: boolean;
  ratePerMinute: number;
  lastTestedAt: string | null;
  lastError: string | null;
  webhookUrl: string;
  webhookToken: string;
  /** Campos comuns (não secretos) */
  values: Record<string, string>;
  /** Segredos salvos, mascarados */
  secrets: Record<string, string>;
  /** Não foi possível descriptografar as credenciais (chave alterada) */
  credentialsUnreadable: boolean;
}

export function toConnectionView(conn: WhatsAppConnection): ConnectionView {
  const def = getProviderDefinition(conn.provider);
  let values: Record<string, string> = {};
  let secrets: Record<string, string> = {};
  let credentialsUnreadable = false;
  try {
    const split = splitCredentials(def?.fields ?? [], decryptCredentials(conn.credentials));
    values = split.values;
    secrets = split.secrets;
  } catch {
    credentialsUnreadable = true;
  }
  return {
    id: conn.id,
    name: conn.name,
    provider: conn.provider as WhatsAppProviderKey,
    status: conn.status as ConnectionStatus,
    phoneNumber: conn.phoneNumber,
    isDefault: conn.isDefault,
    ratePerMinute: conn.ratePerMinute,
    lastTestedAt: conn.lastTestedAt?.toISOString() ?? null,
    lastError: conn.lastError,
    webhookUrl: webhookUrlFor(conn.webhookToken),
    webhookToken: conn.webhookToken,
    values,
    secrets,
    credentialsUnreadable,
  };
}

/** Conexão da campanha (nunca de outra campanha) */
export function findCampaignConnection(campaignId: string, id: string): Promise<WhatsAppConnection | null> {
  return prisma.whatsAppConnection.findFirst({ where: { id, campaignId } });
}

/** Quantos disparos ativos (em andamento, agendados ou pausados) usam a conexão */
export function countActiveBroadcasts(campaignId: string, connectionId: string): Promise<number> {
  return prisma.broadcast.count({
    where: { campaignId, connectionId, status: { in: [...ACTIVE_BROADCAST_STATUSES] } },
  });
}

/**
 * Garante uma conexão padrão na campanha: se nenhuma ativa estiver marcada, promove a primeira
 * conectada (ou, na falta, a primeira não desativada).
 */
export async function ensureDefaultConnection(campaignId: string): Promise<void> {
  const current = await prisma.whatsAppConnection.findFirst({
    where: { campaignId, isDefault: true, status: { not: "DISABLED" } },
    select: { id: true },
  });
  if (current) return;
  const candidate =
    (await prisma.whatsAppConnection.findFirst({
      where: { campaignId, status: "CONNECTED" },
      orderBy: { createdAt: "asc" },
      select: { id: true },
    })) ??
    (await prisma.whatsAppConnection.findFirst({
      where: { campaignId, status: { not: "DISABLED" } },
      orderBy: { createdAt: "asc" },
      select: { id: true },
    }));
  if (!candidate) return;
  await prisma.$transaction([
    prisma.whatsAppConnection.updateMany({ where: { campaignId, isDefault: true }, data: { isDefault: false } }),
    prisma.whatsAppConnection.update({ where: { id: candidate.id }, data: { isDefault: true } }),
  ]);
}

/**
 * Testa a conexão no provedor e grava o resultado: CONNECTED quando passa, ERROR (com lastError)
 * quando falha. Com keepDisabled, uma conexão desativada continua desativada.
 */
export async function runConnectionTest(
  conn: WhatsAppConnection,
  opts: { keepDisabled?: boolean } = {},
): Promise<{ connection: WhatsAppConnection; result: TestResult }> {
  let result: TestResult;
  try {
    result = await providerForConnection(conn).testConnection();
  } catch {
    result = { ok: false, message: "Não foi possível ler as credenciais salvas. Edite a conexão e informe-as novamente." };
  }
  const status: ConnectionStatus =
    opts.keepDisabled && conn.status === "DISABLED" ? "DISABLED" : result.ok ? "CONNECTED" : "ERROR";
  await prisma.whatsAppConnection.update({
    where: { id: conn.id },
    data: {
      status,
      lastTestedAt: new Date(),
      lastError: result.ok ? null : result.message.slice(0, 500),
      ...(result.ok && result.phoneNumber && !conn.phoneNumber ? { phoneNumber: result.phoneNumber.slice(0, 30) } : {}),
    },
  });
  if (status === "CONNECTED") await ensureDefaultConnection(conn.campaignId);
  const connection = (await prisma.whatsAppConnection.findUnique({ where: { id: conn.id } })) ?? conn;
  return { connection, result };
}
