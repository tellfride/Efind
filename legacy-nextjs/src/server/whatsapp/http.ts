// Utilitários HTTP dos provedores de WhatsApp. Puro Node (sem next/*): usado também pelo worker.
// Nunca registre tokens, telefones ou corpos de mensagem em log.
import type { SendResult } from "./types";

export const PROVIDER_TIMEOUT_MS = 15_000;

export interface ProviderHttpResponse<T = unknown> {
  status: number;
  ok: boolean;
  /** Corpo interpretado como JSON (null se vazio ou inválido) */
  data: T | null;
}

/** Erro de rede/timeout ao falar com o provedor (sempre vale tentar de novo) */
export class ProviderNetworkError extends Error {
  constructor(
    message: string,
    readonly timeout: boolean,
  ) {
    super(message);
    this.name = "ProviderNetworkError";
  }
}

/** fetch com timeout de 15 s e leitura tolerante do corpo JSON */
export async function providerRequest<T = unknown>(url: string, init: RequestInit = {}): Promise<ProviderHttpResponse<T>> {
  let res: Response;
  try {
    res = await fetch(url, { ...init, signal: AbortSignal.timeout(PROVIDER_TIMEOUT_MS) });
  } catch (err) {
    const name = err instanceof Error ? err.name : "";
    const timeout = name === "TimeoutError" || name === "AbortError";
    throw new ProviderNetworkError(
      timeout ? "Tempo esgotado ao contatar o provedor" : "Falha de rede ao contatar o provedor",
      timeout,
    );
  }
  const text = await res.text().catch(() => "");
  let data: T | null = null;
  if (text) {
    try {
      data = JSON.parse(text) as T;
    } catch {
      data = null;
    }
  }
  return { status: res.status, ok: res.ok, data };
}

/** Converte exceções de envio em SendResult (rede/timeout = retryable) */
export function sendFailureFromError(err: unknown): SendResult {
  if (err instanceof ProviderNetworkError) return { ok: false, error: err.message, retryable: true };
  return { ok: false, error: "Erro inesperado ao enviar a mensagem", retryable: true };
}

export function testFailureMessage(err: unknown): string {
  if (err instanceof ProviderNetworkError) return err.message;
  return "Erro inesperado ao testar a conexão";
}

export function digitsOnly(value: string | null | undefined): string {
  return (value ?? "").replace(/\D/g, "");
}

/** Telefone de destino aceitável pelos provedores: só dígitos, com DDI, 10 a 15 dígitos */
export function isValidRecipient(value: string): boolean {
  const d = digitsOnly(value);
  return d.length >= 10 && d.length <= 15;
}

export function truncate(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

/** Converte timestamp Unix (segundos, string ou número) em Date */
export function unixToDate(value: unknown): Date | undefined {
  const n = typeof value === "string" ? Number(value) : typeof value === "number" ? value : NaN;
  if (!Number.isFinite(n) || n <= 0) return undefined;
  return new Date(n * 1000);
}
