// Simulador — não envia nenhuma mensagem real. Gera ids "sbx_…", simula falhas conforme a taxa
// configurada e, depois de alguns segundos, eventos de entrega/leitura como se viessem do webhook.
import { randomBytes } from "node:crypto";
import type { OutgoingMessage, ProviderDefinition, SendResult, TestResult, WebhookEvent, WhatsAppProvider } from "../types";
import { parseCloudApiWebhookBody } from "../cloud-api";
import { isValidRecipient } from "../http";

export const SANDBOX_DEFAULT_FAILURE_RATE = 0.05;
export const SANDBOX_MAX_FAILURE_RATE = 0.5;

/** "0,1" | "0.1" | "" → número entre 0 e 0,5 (padrão 0,05) */
export function parseFailureRate(value: string | undefined | null): number {
  const raw = (value ?? "").trim().replace(",", ".");
  if (!raw) return SANDBOX_DEFAULT_FAILURE_RATE;
  const n = Number(raw);
  if (!Number.isFinite(n)) return SANDBOX_DEFAULT_FAILURE_RATE;
  return Math.min(SANDBOX_MAX_FAILURE_RATE, Math.max(0, n));
}

export interface SimulationPlan {
  deliveredAfterMs: number;
  /** null = a mensagem não será lida */
  readAfterMs: number | null;
}

/** Plano de eventos simulados: entregue em 1–4 s; ~60% lidas em 3–10 s (sempre depois da entrega) */
export function planSimulatedStatuses(rng: () => number = Math.random): SimulationPlan {
  const deliveredAfterMs = Math.round(1000 + rng() * 3000);
  const willRead = rng() < 0.6;
  const readAfterMs = willRead ? Math.max(deliveredAfterMs + 500, Math.round(3000 + rng() * 7000)) : null;
  return { deliveredAfterMs, readAfterMs };
}

interface SimulationTarget {
  id: string;
  campaignId: string;
}

async function emit(target: SimulationTarget, events: WebhookEvent[], attempt = 0): Promise<void> {
  try {
    // import dinâmico: mantém o simulador leve (e testável) sem carregar o Prisma
    const { applyWebhookEvents } = await import("../webhook");
    const res = await applyWebhookEvents(target, events);
    // A mensagem pode ainda não ter recebido o providerMessageId no banco: tenta de novo
    if (res.matched === 0 && attempt < 2) {
      const timer = setTimeout(() => void emit(target, events, attempt + 1), 2000);
      timer.unref?.();
    }
  } catch (err) {
    console.error("[whatsapp:simulador] falha ao simular status", err instanceof Error ? err.name : "erro");
  }
}

function schedule(target: SimulationTarget, providerMessageId: string, plan: SimulationPlan) {
  const fire = (status: "DELIVERED" | "READ", delay: number) => {
    const timer = setTimeout(() => {
      void emit(target, [{ kind: "status", providerMessageId, status, timestamp: new Date() }]);
    }, delay);
    timer.unref?.();
  };
  fire("DELIVERED", plan.deliveredAfterMs);
  if (plan.readAfterMs !== null) fire("READ", plan.readAfterMs);
}

class SandboxProvider implements WhatsAppProvider {
  readonly key = "SANDBOX" as const;
  private readonly failureRate: number;
  private readonly target: SimulationTarget | null;

  constructor(creds: Record<string, string>, private readonly rng: () => number = Math.random) {
    this.failureRate = parseFailureRate(creds.failureRate);
    this.target = creds.__connectionId && creds.__campaignId ? { id: creds.__connectionId, campaignId: creds.__campaignId } : null;
  }

  async send(message: OutgoingMessage): Promise<SendResult> {
    if (!isValidRecipient(message.to)) return { ok: false, error: "Número de destino inválido", retryable: false };
    if (!message.text.trim() && !message.template && !message.media) {
      return { ok: false, error: "Mensagem vazia", retryable: false };
    }
    if (this.rng() < this.failureRate) {
      return { ok: false, error: "Falha simulada pelo simulador (nenhuma mensagem real foi enviada)", retryable: false };
    }
    const providerMessageId = `sbx_${randomBytes(12).toString("hex")}`;
    if (this.target) schedule(this.target, providerMessageId, planSimulatedStatuses(this.rng));
    return { ok: true, providerMessageId };
  }

  async testConnection(): Promise<TestResult> {
    return { ok: true, message: "Simulador pronto — nenhuma mensagem real é enviada." };
  }
}

export function createSandboxProvider(creds: Record<string, string>, rng?: () => number): WhatsAppProvider {
  return new SandboxProvider(creds, rng);
}

export const sandboxProvider: ProviderDefinition = {
  key: "SANDBOX",
  label: "Simulador (testes)",
  description:
    "Simula envios, entregas e leituras sem enviar nenhuma mensagem real. Ideal para treinar a equipe e testar disparos antes de usar a API oficial.",
  official: false,
  setupSteps: [
    "Nenhuma credencial é necessária: o simulador funciona imediatamente.",
    "Os disparos feitos por esta conexão aparecem como enviados, entregues e lidos alguns segundos depois — sem nenhuma mensagem real.",
    "Use a taxa de falhas para ver como o sistema trata erros de envio.",
    "Antes da campanha, cadastre uma conexão oficial (Meta, 360dialog ou Twilio) e defina-a como padrão.",
  ],
  fields: [
    {
      name: "failureRate",
      label: "Taxa de falhas simuladas",
      type: "text",
      required: false,
      placeholder: "0,05",
      help: "Proporção de envios que falham de propósito, de 0 a 0,5 (ex.: 0,05 = 5%).",
    },
  ],
  requiresApprovedTemplate: false,
  create: (credentials) => new SandboxProvider(credentials),
  // Aceita payloads no formato da Cloud API (útil para testar o webhook localmente)
  parseWebhook: (req) => parseCloudApiWebhookBody(req.rawBody),
};
