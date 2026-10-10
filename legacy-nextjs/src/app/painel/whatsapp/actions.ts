"use server";

// Server Actions das conexões de WhatsApp. Toda ação exige whatsapp.edit e opera apenas em
// conexões da campanha do usuário logado. Segredos nunca entram na auditoria nem voltam ao navegador.
import { revalidatePath } from "next/cache";
import { z } from "zod";
import { prisma } from "@/lib/db";
import { authorize } from "@/lib/auth";
import { audit } from "@/lib/audit";
import { encryptJson, randomToken } from "@/lib/crypto";
import { actionError, actionOk, zodToActionError, type ActionResult } from "@/lib/action-result";
import { WHATSAPP_PROVIDERS, type ConnectionStatus } from "@/lib/constants";
import { normalizeBrPhone } from "@/lib/phone";
import { rateLimit } from "@/lib/rate-limit";
import { decryptCredentials, getProviderDefinition, providerForConnection, webhookUrlFor } from "@/server/whatsapp/registry";
import { CLEAR_FIELD_PREFIX, CREDENTIAL_FIELD_PREFIX, resolveCredentials } from "@/server/whatsapp/credentials";
import {
  countActiveBroadcasts,
  ensureDefaultConnection,
  findCampaignConnection,
  runConnectionTest,
  toConnectionView,
  type ConnectionView,
} from "@/server/whatsapp/connections";
import { registerDialog360Webhook } from "@/server/whatsapp/providers/dialog360";
import type { OutgoingMessage } from "@/server/whatsapp/types";

const PANEL_PATH = "/painel/whatsapp";
const MAX_CONNECTIONS_PER_CAMPAIGN = 20;

const idSchema = z.string().trim().min(1, "Conexão inválida").max(64, "Conexão inválida");

function revalidate() {
  revalidatePath(PANEL_PATH, "layout");
}

function formString(formData: FormData, key: string): string {
  const v = formData.get(key);
  return typeof v === "string" ? v : "";
}

// ---------------- Criar / editar ----------------

const saveSchema = z.object({
  provider: z.enum(WHATSAPP_PROVIDERS, { errorMap: () => ({ message: "Escolha um provedor" }) }),
  connectionId: z
    .string()
    .trim()
    .max(64)
    .transform((v) => v || undefined),
  name: z.string().trim().min(2, "Informe um nome com pelo menos 2 caracteres").max(80, "Use no máximo 80 caracteres"),
  phoneNumber: z
    .string()
    .trim()
    .max(30, "Use no máximo 30 caracteres")
    .transform((v) => v || null),
  ratePerMinute: z.coerce
    .number({ invalid_type_error: "Informe um número" })
    .int("Use um número inteiro")
    .min(1, "Mínimo de 1 mensagem por minuto")
    .max(600, "Máximo de 600 mensagens por minuto"),
});

export async function saveConnectionAction(
  _prev: ActionResult<ConnectionView>,
  formData: FormData,
): Promise<ActionResult<ConnectionView>> {
  const auth = await authorize("whatsapp", "edit");
  if (!auth.ok) return actionError(auth.error);
  const { user } = auth;

  const parsed = saveSchema.safeParse({
    provider: formString(formData, "provider"),
    connectionId: formString(formData, "connectionId"),
    name: formString(formData, "name"),
    phoneNumber: formString(formData, "phoneNumber"),
    ratePerMinute: formString(formData, "ratePerMinute"),
  });
  if (!parsed.success) return zodToActionError(parsed.error);
  const data = parsed.data;

  const def = getProviderDefinition(data.provider);
  if (!def) return actionError("Provedor indisponível.");

  const existing = data.connectionId ? await findCampaignConnection(user.campaignId, data.connectionId) : null;
  if (data.connectionId && !existing) return actionError("Conexão não encontrada.");
  if (existing && existing.provider !== data.provider) {
    return actionError("Não é possível trocar o provedor de uma conexão existente. Crie uma nova conexão.");
  }

  let existingCredentials: Record<string, string> = {};
  if (existing) {
    try {
      existingCredentials = decryptCredentials(existing.credentials);
    } catch {
      existingCredentials = {}; // chave alterada: o usuário precisa informar os segredos de novo
    }
  }

  const input: Record<string, string> = {};
  for (const f of def.fields) input[f.name] = formString(formData, `${CREDENTIAL_FIELD_PREFIX}${f.name}`);
  const clear = def.fields.filter((f) => formString(formData, `${CLEAR_FIELD_PREFIX}${f.name}`) === "on").map((f) => f.name);
  const resolved = resolveCredentials(def, input, existingCredentials, clear);
  if (!resolved.ok) return actionError("Verifique os campos destacados.", resolved.fieldErrors);

  let encrypted: string;
  try {
    encrypted = encryptJson(resolved.credentials);
  } catch {
    return actionError("A chave de criptografia do servidor (ENCRYPTION_KEY) não está configurada. Fale com o suporte.");
  }

  // ---- Nova conexão: rascunho com token de webhook gerado no servidor ----
  if (!existing) {
    const total = await prisma.whatsAppConnection.count({ where: { campaignId: user.campaignId } });
    if (total >= MAX_CONNECTIONS_PER_CAMPAIGN) {
      return actionError(`Limite de ${MAX_CONNECTIONS_PER_CAMPAIGN} conexões por campanha atingido. Exclua conexões sem uso.`);
    }
    const created = await prisma.whatsAppConnection.create({
      data: {
        campaignId: user.campaignId,
        name: data.name,
        provider: data.provider,
        status: "DRAFT",
        phoneNumber: data.phoneNumber,
        credentials: encrypted,
        webhookToken: randomToken(),
        ratePerMinute: data.ratePerMinute,
      },
    });
    await ensureDefaultConnection(user.campaignId);
    const conn = (await prisma.whatsAppConnection.findUnique({ where: { id: created.id } })) ?? created;
    await audit({
      action: "whatsapp.connection_create",
      campaignId: user.campaignId,
      userId: user.id,
      entity: "WhatsAppConnection",
      entityId: conn.id,
      details: { provider: conn.provider, name: conn.name },
    });
    revalidate();
    return actionOk("Rascunho salvo. Agora configure o webhook.", toConnectionView(conn));
  }

  // ---- Edição: segredos em branco foram mantidos por resolveCredentials ----
  const changedFields = [
    ...(existing.name !== data.name ? ["name"] : []),
    ...(existing.phoneNumber !== data.phoneNumber ? ["phoneNumber"] : []),
    ...(existing.ratePerMinute !== data.ratePerMinute ? ["ratePerMinute"] : []),
    ...resolved.changed.map((f) => `credentials.${f}`),
  ];
  let conn = await prisma.whatsAppConnection.update({
    where: { id: existing.id },
    data: {
      name: data.name,
      phoneNumber: data.phoneNumber,
      ratePerMinute: data.ratePerMinute,
      ...(resolved.changed.length ? { credentials: encrypted } : {}),
    },
  });

  let message = changedFields.length ? "Conexão atualizada." : "Nenhuma alteração.";
  // Credenciais novas invalidam o último teste: conexões em uso são testadas de novo na hora
  if (resolved.changed.length && (existing.status === "CONNECTED" || existing.status === "ERROR")) {
    const tested = await runConnectionTest(conn);
    conn = tested.connection;
    message = tested.result.ok
      ? "Credenciais atualizadas e conexão testada com sucesso."
      : `Credenciais salvas, mas o teste falhou: ${tested.result.message}`;
  }

  if (changedFields.length) {
    await audit({
      action: "whatsapp.connection_update",
      campaignId: user.campaignId,
      userId: user.id,
      entity: "WhatsAppConnection",
      entityId: conn.id,
      details: { provider: conn.provider, changedFields, status: conn.status },
    });
  }
  revalidate();
  return actionOk(message, toConnectionView(conn));
}

// ---------------- Testes ----------------

export async function testConnectionAction(
  connectionId: string,
): Promise<ActionResult<{ connection: ConnectionView; testedOk: boolean }>> {
  const auth = await authorize("whatsapp", "edit");
  if (!auth.ok) return actionError(auth.error);
  const { user } = auth;
  const id = idSchema.safeParse(connectionId);
  if (!id.success) return actionError("Conexão inválida.");

  const conn = await findCampaignConnection(user.campaignId, id.data);
  if (!conn) return actionError("Conexão não encontrada.");

  const limit = rateLimit(`wa-test:${user.id}`, 30, 10 * 60_000);
  if (!limit.ok) return actionError(`Muitos testes seguidos. Tente novamente em ${Math.ceil(limit.retryAfterSeconds / 60)} min.`);

  const { connection, result } = await runConnectionTest(conn, { keepDisabled: true });
  await audit({
    action: "whatsapp.connection_test",
    campaignId: user.campaignId,
    userId: user.id,
    entity: "WhatsAppConnection",
    entityId: conn.id,
    details: { provider: conn.provider, kind: "connection", ok: result.ok },
  });
  revalidate();
  const payload = { connection: toConnectionView(connection), testedOk: result.ok };
  return result.ok ? actionOk(result.message, payload) : { ok: false, error: result.message, data: payload };
}

const testMessageSchema = z
  .object({
    connectionId: idSchema,
    to: z.string().trim().min(1, "Informe o número de destino").max(30, "Número inválido"),
    text: z.string().trim().max(1000, "Use no máximo 1000 caracteres"),
    useTemplate: z.boolean().default(false),
  })
  .refine((d) => d.useTemplate || d.text.length > 0, { message: "Escreva a mensagem de teste", path: ["text"] });

export async function sendTestMessageAction(input: {
  connectionId: string;
  to: string;
  text: string;
  useTemplate?: boolean;
}): Promise<ActionResult<{ providerMessageId?: string }>> {
  const auth = await authorize("whatsapp", "edit");
  if (!auth.ok) return actionError(auth.error);
  const { user } = auth;

  const parsed = testMessageSchema.safeParse(input);
  if (!parsed.success) return zodToActionError(parsed.error);
  const to = normalizeBrPhone(parsed.data.to);
  if (!to) return actionError("Telefone inválido.", { to: ["Informe um celular com DDD, ex.: (11) 98765-4321"] });

  const conn = await findCampaignConnection(user.campaignId, parsed.data.connectionId);
  if (!conn) return actionError("Conexão não encontrada.");
  if (conn.status === "DISABLED") return actionError("Ative a conexão antes de enviar uma mensagem de teste.");

  const limit = rateLimit(`wa-test-msg:${user.id}`, 10, 10 * 60_000);
  if (!limit.ok) {
    return actionError(`Limite de mensagens de teste atingido. Tente novamente em ${Math.ceil(limit.retryAfterSeconds / 60)} min.`);
  }

  const useTemplate = parsed.data.useTemplate && conn.provider === "META_CLOUD";
  const message: OutgoingMessage = useTemplate
    ? { to, text: "", template: { name: "hello_world", language: "en_US", parameters: [] } }
    : { to, text: parsed.data.text };

  let result: { ok: boolean; providerMessageId?: string; error?: string };
  try {
    // Sem id/token: mensagem avulsa, fora de disparos (nada a atualizar por webhook)
    result = await providerForConnection({ provider: conn.provider, credentials: conn.credentials }).send(message);
  } catch {
    result = { ok: false, error: "Não foi possível ler as credenciais salvas. Edite a conexão e informe-as novamente." };
  }

  await audit({
    action: "whatsapp.connection_test",
    campaignId: user.campaignId,
    userId: user.id,
    entity: "WhatsAppConnection",
    entityId: conn.id,
    details: { provider: conn.provider, kind: "message", ok: result.ok, template: useTemplate },
  });

  if (!result.ok) return actionError(result.error ?? "O provedor recusou a mensagem.");
  return actionOk(
    conn.provider === "SANDBOX"
      ? "Envio simulado com sucesso — nenhuma mensagem real foi enviada."
      : "Mensagem aceita pelo provedor. Confira o WhatsApp do número informado.",
    { providerMessageId: result.providerMessageId },
  );
}

// ---------------- Padrão / ativar / desativar / excluir ----------------

export async function setDefaultConnectionAction(connectionId: string): Promise<ActionResult> {
  const auth = await authorize("whatsapp", "edit");
  if (!auth.ok) return actionError(auth.error);
  const { user } = auth;
  const id = idSchema.safeParse(connectionId);
  if (!id.success) return actionError("Conexão inválida.");

  const conn = await findCampaignConnection(user.campaignId, id.data);
  if (!conn) return actionError("Conexão não encontrada.");
  if (conn.status !== "CONNECTED") return actionError("Teste a conexão com sucesso antes de defini-la como padrão.");
  if (conn.isDefault) return actionOk("Esta já é a conexão padrão.");

  await prisma.$transaction([
    prisma.whatsAppConnection.updateMany({ where: { campaignId: user.campaignId, isDefault: true }, data: { isDefault: false } }),
    prisma.whatsAppConnection.update({ where: { id: conn.id }, data: { isDefault: true } }),
  ]);
  await audit({
    action: "whatsapp.connection_update",
    campaignId: user.campaignId,
    userId: user.id,
    entity: "WhatsAppConnection",
    entityId: conn.id,
    details: { provider: conn.provider, changedFields: ["isDefault"], isDefault: true },
  });
  revalidate();
  return actionOk(`"${conn.name}" agora é a conexão padrão dos disparos.`);
}

export async function setConnectionEnabledAction(
  connectionId: string,
  enabled: boolean,
): Promise<ActionResult<{ status: ConnectionStatus }>> {
  const auth = await authorize("whatsapp", "edit");
  if (!auth.ok) return actionError(auth.error);
  const { user } = auth;
  const id = idSchema.safeParse(connectionId);
  if (!id.success || typeof enabled !== "boolean") return actionError("Requisição inválida.");

  const conn = await findCampaignConnection(user.campaignId, id.data);
  if (!conn) return actionError("Conexão não encontrada.");

  if (!enabled) {
    if (conn.status === "DISABLED") return actionOk("A conexão já está desativada.", { status: "DISABLED" });
    await prisma.whatsAppConnection.update({ where: { id: conn.id }, data: { status: "DISABLED", isDefault: false } });
    await ensureDefaultConnection(user.campaignId);
    await audit({
      action: "whatsapp.connection_update",
      campaignId: user.campaignId,
      userId: user.id,
      entity: "WhatsAppConnection",
      entityId: conn.id,
      details: { provider: conn.provider, changedFields: ["status"], status: "DISABLED" },
    });
    revalidate();
    return actionOk("Conexão desativada. Ela não será usada em novos envios.", { status: "DISABLED" });
  }

  if (conn.status !== "DISABLED") return actionOk("A conexão já está ativa.", { status: conn.status as ConnectionStatus });
  // Reativar = testar de novo: CONNECTED se passar, ERROR (com o motivo) se falhar
  const { connection, result } = await runConnectionTest(conn);
  await audit({
    action: "whatsapp.connection_update",
    campaignId: user.campaignId,
    userId: user.id,
    entity: "WhatsAppConnection",
    entityId: conn.id,
    details: { provider: conn.provider, changedFields: ["status"], status: connection.status },
  });
  revalidate();
  const status = connection.status as ConnectionStatus;
  return actionOk(
    result.ok ? "Conexão reativada e testada com sucesso." : `Conexão reativada, mas o teste falhou: ${result.message}`,
    { status },
  );
}

export async function deleteConnectionAction(connectionId: string): Promise<ActionResult> {
  const auth = await authorize("whatsapp", "edit");
  if (!auth.ok) return actionError(auth.error);
  const { user } = auth;
  const id = idSchema.safeParse(connectionId);
  if (!id.success) return actionError("Conexão inválida.");

  const conn = await findCampaignConnection(user.campaignId, id.data);
  if (!conn) return actionError("Conexão não encontrada.");

  const active = await countActiveBroadcasts(user.campaignId, conn.id);
  if (active > 0) {
    return actionError(
      `Esta conexão está sendo usada por ${active} disparo(s) em andamento, agendado(s) ou pausado(s). Conclua ou cancele esses disparos antes de excluí-la.`,
    );
  }

  await prisma.whatsAppConnection.delete({ where: { id: conn.id } });
  await ensureDefaultConnection(user.campaignId);
  await audit({
    action: "whatsapp.connection_delete",
    campaignId: user.campaignId,
    userId: user.id,
    entity: "WhatsAppConnection",
    entityId: conn.id,
    details: { provider: conn.provider, name: conn.name },
  });
  revalidate();
  return actionOk(`Conexão "${conn.name}" excluída.`);
}

// ---------------- Webhook automático (360dialog) ----------------

export async function registerWebhookAction(connectionId: string): Promise<ActionResult> {
  const auth = await authorize("whatsapp", "edit");
  if (!auth.ok) return actionError(auth.error);
  const { user } = auth;
  const id = idSchema.safeParse(connectionId);
  if (!id.success) return actionError("Conexão inválida.");

  const conn = await findCampaignConnection(user.campaignId, id.data);
  if (!conn) return actionError("Conexão não encontrada.");
  if (conn.provider !== "DIALOG360") return actionError("O registro automático de webhook está disponível apenas para a 360dialog.");

  const url = webhookUrlFor(conn.webhookToken);
  if (!url.startsWith("https://") || /\/\/(localhost|127\.0\.0\.1)/.test(url)) {
    return actionError("Configure APP_URL com o endereço público HTTPS do E-Find antes de registrar o webhook.");
  }

  let credentials: Record<string, string>;
  try {
    credentials = decryptCredentials(conn.credentials);
  } catch {
    return actionError("Não foi possível ler as credenciais salvas. Edite a conexão e informe-as novamente.");
  }
  const result = await registerDialog360Webhook(credentials, url);
  if (result.ok) {
    await audit({
      action: "whatsapp.connection_update",
      campaignId: user.campaignId,
      userId: user.id,
      entity: "WhatsAppConnection",
      entityId: conn.id,
      details: { provider: conn.provider, changedFields: ["webhook"], webhookRegistered: true },
    });
  }
  return result.ok ? actionOk(result.message) : actionError(result.message);
}
