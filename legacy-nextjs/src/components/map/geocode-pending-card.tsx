"use client";

// Card do ADMIN: fila de geocodificação da campanha + "Localizar pendentes agora".
import * as React from "react";
import { useActionState } from "react";
import { useRouter } from "next/navigation";
import { MapPinned, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { formatNumber } from "@/lib/utils";
import type { ActionResult } from "@/lib/action-result";
import type { GeocodeRunResult, GeoQueueCounts } from "@/server/map/types";
import { geocodePendingAction } from "@/app/painel/mapa/actions";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { SubmitButton } from "@/components/ui/client";

const INITIAL: ActionResult<GeocodeRunResult> = { ok: false };

export function GeocodePendingCard({ queue, onDone }: { queue: GeoQueueCounts; onDone: () => void }) {
  const router = useRouter();
  const [state, formAction] = useActionState(geocodePendingAction, INITIAL);
  const handled = React.useRef(state);
  const onDoneRef = React.useRef(onDone);
  React.useEffect(() => {
    onDoneRef.current = onDone;
  }, [onDone]);

  React.useEffect(() => {
    if (handled.current === state) return;
    handled.current = state;
    if (state.ok) {
      toast.success(state.message ?? "Localização concluída.");
      onDoneRef.current();
      router.refresh();
    } else if (state.error) {
      toast.error(state.error);
    }
  }, [state, router]);

  const total = queue.pending + queue.failed;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <MapPinned className="size-4 text-brand-600" aria-hidden />
          Localização pendente
        </CardTitle>
        <CardDescription>Eleitores da campanha aguardando localização pelo CEP ou cuja busca falhou.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-lg bg-slate-50 px-3 py-2">
            <p className="text-xs text-slate-500">Na fila</p>
            <p className="text-xl font-bold text-slate-900 tabular-nums">{formatNumber(queue.pending)}</p>
          </div>
          <div className="rounded-lg bg-slate-50 px-3 py-2">
            <p className="text-xs text-slate-500">Não localizados</p>
            <p className="text-xl font-bold text-slate-900 tabular-nums">{formatNumber(queue.failed)}</p>
          </div>
        </div>
        <p className="text-xs text-slate-500">
          {total > 0
            ? "A localização roda automaticamente em segundo plano. O botão processa até 15 eleitores agora e devolve à fila os que falharam."
            : "Todos os eleitores com endereço já foram processados."}
        </p>
      </CardContent>
      <CardFooter>
        <form action={formAction} className="w-full">
          <SubmitButton className="w-full" pendingText="Localizando..." disabled={total === 0}>
            <RefreshCw aria-hidden /> Localizar pendentes agora
          </SubmitButton>
        </form>
      </CardFooter>
    </Card>
  );
}
