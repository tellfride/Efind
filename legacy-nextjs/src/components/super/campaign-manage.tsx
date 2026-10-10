"use client";

import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, PauseCircle, PlayCircle, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FormMessage, Input } from "@/components/ui/form";
import { Modal } from "@/components/ui/client";
import { Alert } from "@/components/ui/misc";
import { deleteCampaignAction, setCampaignStatusAction, updateCampaignAction } from "@/server/super/campaign-actions";
import { CampaignFields, type CampaignFieldValues } from "./campaign-fields";
import { useActionForm } from "./use-action-form";

/** Edição dos dados da campanha */
export function CampaignEditForm({ campaignId, values }: { campaignId: string; values: CampaignFieldValues }) {
  const { state, onSubmit, pending } = useActionForm<undefined>(updateCampaignAction);
  const router = useRouter();

  useEffect(() => {
    if (state.ok) {
      toast.success(state.message ?? "Dados atualizados");
      router.refresh();
    }
  }, [state, router]);

  return (
    <Card>
      <form onSubmit={onSubmit} noValidate>
        <CardHeader>
          <CardTitle>Dados do candidato e da campanha</CardTitle>
          <CardDescription>As alterações aparecem imediatamente no painel da equipe.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {!state.ok && <FormMessage result={state} />}
          <input type="hidden" name="campaignId" value={campaignId} />
          <CampaignFields defaults={values} errors={state.fieldErrors} />
        </CardContent>
        <CardFooter>
          <Button type="submit" loading={pending}>
            {pending ? "Salvando..." : "Salvar alterações"}
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
}

/** Suspender / reativar a campanha (com confirmação) */
export function CampaignStatusControl({
  campaignId,
  ballotName,
  status,
}: {
  campaignId: string;
  ballotName: string;
  status: string;
}) {
  const [open, setOpen] = useState(false);
  const [pending, startTransition] = useTransition();
  const router = useRouter();
  const suspending = status === "ACTIVE";

  const confirm = () =>
    startTransition(async () => {
      const res = await setCampaignStatusAction({ campaignId, status: suspending ? "SUSPENDED" : "ACTIVE" });
      if (res.ok) {
        toast.success(res.message ?? "Status atualizado");
        setOpen(false);
        router.refresh();
      } else {
        toast.error(res.error ?? "Não foi possível alterar o status");
      }
    });

  return (
    <>
      <Button variant={suspending ? "outline" : "success"} onClick={() => setOpen(true)}>
        {suspending ? <PauseCircle aria-hidden /> : <PlayCircle aria-hidden />}
        {suspending ? "Suspender campanha" : "Reativar campanha"}
      </Button>
      <Modal
        open={open}
        onClose={() => !pending && setOpen(false)}
        title={suspending ? "Suspender campanha?" : "Reativar campanha?"}
        description={ballotName}
        footer={
          <>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={pending}>
              Cancelar
            </Button>
            <Button variant={suspending ? "danger" : "success"} onClick={confirm} loading={pending}>
              {suspending ? "Suspender" : "Reativar"}
            </Button>
          </>
        }
      >
        {suspending ? (
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-slate-600">
            <li>Ninguém da equipe (administradores, coordenadores e cabos) conseguirá entrar; sessões abertas são encerradas.</li>
            <li>Disparos de WhatsApp em andamento serão pausados.</li>
            <li>Nenhum dado é apagado. Você pode reativar a campanha a qualquer momento.</li>
          </ul>
        ) : (
          <p className="text-sm text-slate-600">
            A equipe volta a ter acesso ao painel. Disparos pausados pela suspensão continuam pausados até que a campanha os retome.
          </p>
        )}
      </Modal>
    </>
  );
}

/** Zona de perigo: exclusão definitiva exigindo digitar o identificador (slug) */
export function CampaignDangerZone({ campaignId, slug, ballotName }: { campaignId: string; slug: string; ballotName: string }) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const { state, onSubmit, pending } = useActionForm<undefined>(deleteCampaignAction);

  const close = () => {
    if (pending) return;
    setOpen(false);
    setTyped("");
  };

  return (
    <Card className="border-red-200">
      <CardHeader className="border-red-100">
        <CardTitle className="flex items-center gap-2 text-red-700">
          <AlertTriangle className="size-4" aria-hidden /> Zona de perigo
        </CardTitle>
        <CardDescription>
          Excluir a campanha apaga definitivamente eleitores, equipe, modelos, disparos, conexões de WhatsApp, dashboards e a auditoria da
          campanha. Não é possível desfazer.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-slate-600">
          Prefere apenas bloquear o acesso? Use <strong>Suspender campanha</strong> no topo da página.
        </p>
        <Button variant="danger" onClick={() => setOpen(true)}>
          <Trash2 aria-hidden /> Excluir campanha
        </Button>
      </CardContent>

      <Modal open={open} onClose={close} title="Excluir campanha definitivamente" description={ballotName}>
        <form onSubmit={onSubmit} className="space-y-4">
          <Alert tone="danger" title="Esta ação não pode ser desfeita.">
            Todos os dados da campanha, inclusive os cadastros de eleitores, serão apagados.
          </Alert>
          <input type="hidden" name="campaignId" value={campaignId} />
          <Field
            label={
              <>
                Para confirmar, digite <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-red-700">{slug}</code>
              </>
            }
            htmlFor="confirmSlug"
            error={state.fieldErrors?.confirmSlug}
          >
            <Input
              id="confirmSlug"
              name="confirmSlug"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              autoComplete="off"
              autoCapitalize="off"
              spellCheck={false}
              autoFocus
            />
          </Field>
          {!state.ok && !state.fieldErrors && <FormMessage result={state} />}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button variant="outline" onClick={close} disabled={pending}>
              Cancelar
            </Button>
            <Button type="submit" variant="danger" loading={pending} disabled={typed.trim() !== slug}>
              <Trash2 aria-hidden /> Excluir definitivamente
            </Button>
          </div>
        </form>
      </Modal>
    </Card>
  );
}
