// Webhook público dos provedores de WhatsApp: /api/webhooks/whatsapp/{webhookToken}
// O token aleatório da URL identifica a conexão (e a campanha); a assinatura do provedor, quando
// existe, é validada antes de qualquer processamento.
import { prisma } from "@/lib/db";
import { decryptCredentials, getProviderDefinition } from "@/server/whatsapp/registry";
import { applyWebhookEvents } from "@/server/whatsapp/webhook";
import type { WebhookRequest } from "@/server/whatsapp/types";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const MAX_BODY_BYTES = 1_000_000;
const TOKEN_RE = /^[A-Za-z0-9_-]{16,128}$/;
const EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>';

type RouteContext = { params: Promise<{ token: string }> };

function reply(body: string, status = 200, contentType = "text/plain; charset=utf-8"): Response {
  return new Response(body, { status, headers: { "Content-Type": contentType, "Cache-Control": "no-store" } });
}

async function loadConnection(token: string) {
  if (!TOKEN_RE.test(token)) return null;
  const conn = await prisma.whatsAppConnection.findUnique({
    where: { webhookToken: token },
    select: { id: true, campaignId: true, provider: true, credentials: true, webhookToken: true, status: true },
  });
  if (!conn || conn.status === "DISABLED") return null;
  return conn;
}

function readCredentials(encrypted: string, provider: string): Record<string, string> | null {
  try {
    return decryptCredentials(encrypted);
  } catch {
    console.error("[whatsapp:webhook] não foi possível descriptografar as credenciais", provider);
    return null;
  }
}

/** Verificação do webhook (handshake da Meta) */
export async function GET(req: Request, { params }: RouteContext): Promise<Response> {
  const { token } = await params;
  const conn = await loadConnection(token);
  if (!conn) return reply("Not found", 404);
  const def = getProviderDefinition(conn.provider);
  if (!def?.handleVerification) return reply("Method not allowed", 405);
  const credentials = readCredentials(conn.credentials, conn.provider);
  if (!credentials) return reply("Server error", 500);

  const wreq: WebhookRequest = { method: "GET", url: new URL(req.url), headers: req.headers, rawBody: "" };
  const res = def.handleVerification(wreq, credentials, conn.webhookToken);
  if (!res) return reply("Bad request", 400);
  return reply(res.body, res.status, res.contentType ?? "text/plain; charset=utf-8");
}

/** Eventos: status de mensagens e mensagens recebidas */
export async function POST(req: Request, { params }: RouteContext): Promise<Response> {
  const { token } = await params;
  const conn = await loadConnection(token);
  if (!conn) return reply("Not found", 404);
  const def = getProviderDefinition(conn.provider);
  if (!def) return reply("Not found", 404);

  const declaredLength = Number(req.headers.get("content-length") ?? 0);
  if (declaredLength > MAX_BODY_BYTES) return reply("Payload too large", 413);
  const rawBody = await req.text();
  if (Buffer.byteLength(rawBody, "utf8") > MAX_BODY_BYTES) return reply("Payload too large", 413);

  const credentials = readCredentials(conn.credentials, conn.provider);
  if (!credentials) return reply("Server error", 500);

  const wreq: WebhookRequest = { method: "POST", url: new URL(req.url), headers: req.headers, rawBody };
  if (def.verifySignature && !def.verifySignature(wreq, credentials)) return reply("Invalid signature", 401);

  try {
    const events = def.parseWebhook(wreq);
    if (events.length) await applyWebhookEvents({ id: conn.id, campaignId: conn.campaignId }, events);
  } catch (err) {
    // Assinatura válida: responde 200 para o provedor não reenviar em loop; registra sem dados pessoais
    console.error("[whatsapp:webhook] falha ao processar eventos", conn.provider, err instanceof Error ? err.name : "erro");
  }

  // A Twilio espera TwiML nas mensagens recebidas; resposta vazia = nenhuma resposta automática
  if (conn.provider === "TWILIO") return reply(EMPTY_TWIML, 200, "text/xml; charset=utf-8");
  return reply("ok");
}
