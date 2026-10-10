"use client";

// Busca os dados dos widgets em lote (POST /api/painel/dashboard/data), com cache por "chave de dados":
// mudar título/tamanho não recarrega; mudar período, limite ou filtros recarrega só aquele widget.
import * as React from "react";
import {
  isWidgetError,
  widgetDataKey,
  type DashboardDataResponse,
  type DashboardWidget,
  type WidgetData,
} from "@/lib/dashboard-types";

export type WidgetEntry =
  | { status: "loading" }
  | { status: "ok"; data: WidgetData }
  | { status: "error"; error: string };

const ENDPOINT = "/api/painel/dashboard/data";

async function readError(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { error?: unknown };
    if (typeof body.error === "string") return body.error;
  } catch {
    // corpo não é JSON
  }
  return res.status === 401 ? "Sessão expirada. Faça login novamente." : "Não foi possível carregar os dados.";
}

export function useDashboardData(
  widgets: DashboardWidget[],
  { debounceMs = 0, autoRefreshMs = 0 }: { debounceMs?: number; autoRefreshMs?: number } = {},
) {
  const [entries, setEntries] = React.useState<Record<string, WidgetEntry>>({});
  const [updatedAt, setUpdatedAt] = React.useState<Date | null>(null);
  const [version, setVersion] = React.useState(0);
  const entriesRef = React.useRef(entries);
  const inflight = React.useRef(new Set<string>());
  const generation = React.useRef(0);

  React.useEffect(() => {
    entriesRef.current = entries;
  }, [entries]);

  // Widgets com dados (o recado não consulta o servidor), um por chave
  const keyed = React.useMemo(() => {
    const map = new Map<string, DashboardWidget>();
    for (const w of widgets) {
      if (w.type === "note") continue;
      const key = widgetDataKey(w);
      if (!map.has(key)) map.set(key, w);
    }
    return map;
  }, [widgets]);
  const signature = React.useMemo(() => [...keyed.keys()].join("\n"), [keyed]);
  const keyedRef = React.useRef(keyed);
  React.useEffect(() => {
    keyedRef.current = keyed;
  }, [keyed]);

  React.useEffect(() => {
    const current = keyedRef.current;
    const missing = [...current.entries()].filter(([key]) => !entriesRef.current[key] && !inflight.current.has(key));
    if (!missing.length) return;

    const gen = generation.current;
    const timer = window.setTimeout(() => {
      const keys = missing.map(([key]) => key);
      keys.forEach((k) => inflight.current.add(k));
      setEntries((prev) => {
        const next = { ...prev };
        for (const k of keys) next[k] = { status: "loading" };
        return next;
      });
      const idToKey = new Map(missing.map(([key, w]) => [w.id, key]));
      fetch(ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ widgets: missing.map(([, w]) => w) }),
        cache: "no-store",
      })
        .then(async (res) => {
          if (!res.ok) throw new Error(await readError(res));
          return (await res.json()) as DashboardDataResponse;
        })
        .then((json) => {
          if (gen !== generation.current) return;
          setEntries((prev) => {
            const next: Record<string, WidgetEntry> = {};
            // Mantém apenas as chaves ainda em uso (descarta dados de configurações antigas)
            for (const [k, v] of Object.entries(prev)) if (keyedRef.current.has(k)) next[k] = v;
            for (const [id, key] of idToKey) {
              const result = json[id];
              if (!result) next[key] = { status: "error", error: "Sem resposta para este widget." };
              else if (isWidgetError(result)) next[key] = { status: "error", error: result.error };
              else next[key] = { status: "ok", data: result };
            }
            return next;
          });
          setUpdatedAt(new Date());
        })
        .catch((err: unknown) => {
          if (gen !== generation.current) return;
          const message = err instanceof Error && err.message ? err.message : "Não foi possível carregar os dados.";
          setEntries((prev) => {
            const next = { ...prev };
            for (const k of keys) next[k] = { status: "error", error: message };
            return next;
          });
        })
        .finally(() => {
          if (gen === generation.current) keys.forEach((k) => inflight.current.delete(k));
        });
    }, debounceMs);
    return () => window.clearTimeout(timer);
  }, [signature, version, debounceMs]);

  /** Recarrega todos os widgets */
  const refresh = React.useCallback(() => {
    generation.current += 1;
    inflight.current.clear();
    entriesRef.current = {};
    setEntries({});
    setVersion((v) => v + 1);
  }, []);

  /** Recarrega um widget (ex.: botão "Tentar novamente") */
  const retry = React.useCallback((widget: DashboardWidget) => {
    const key = widgetDataKey(widget);
    inflight.current.delete(key);
    const next = { ...entriesRef.current };
    delete next[key];
    entriesRef.current = next;
    setEntries(next);
    setVersion((v) => v + 1);
  }, []);

  React.useEffect(() => {
    if (!autoRefreshMs) return;
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") refresh();
    }, autoRefreshMs);
    return () => window.clearInterval(id);
  }, [autoRefreshMs, refresh]);

  const entryFor = React.useCallback(
    (widget: DashboardWidget): WidgetEntry | undefined => (widget.type === "note" ? undefined : entries[widgetDataKey(widget)]),
    [entries],
  );

  const loading = Object.values(entries).some((e) => e.status === "loading");
  return { entryFor, refresh, retry, updatedAt, loading };
}
