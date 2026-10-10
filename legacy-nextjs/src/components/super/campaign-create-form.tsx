"use client";

import { useEffect, useRef, useState } from "react";
import { CheckCircle2, Plus, ShieldCheck, UserCog } from "lucide-react";
import { toast } from "sonner";
import { Button, ButtonLink } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { FormMessage } from "@/components/ui/form";
import { createCampaignAction } from "@/server/super/campaign-actions";
import type { CreatedCampaign } from "@/server/super/validation";
import { AccountFields } from "./account-fields";
import { CampaignFields } from "./campaign-fields";
import { CredentialsPanel } from "./credentials-panel";
import { useActionForm } from "./use-action-form";

/** Criação de campanha + 1º administrador. "Criar outra" remonta o formulário limpo. */
export function CampaignCreateWizard() {
  const [round, setRound] = useState(0);
  return <CampaignCreateForm key={round} onRestart={() => setRound((r) => r + 1)} />;
}

function CampaignCreateForm({ onRestart }: { onRestart: () => void }) {
  const { state, onSubmit, pending } = useActionForm<CreatedCampaign>(createCampaignAction);
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    if (state.ok) {
      toast.success(state.message ?? "Campanha criada");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } else if (state.fieldErrors) {
      // Leva o usuário ao primeiro campo com erro
      formRef.current?.querySelector<HTMLElement>("[aria-invalid='true']")?.focus();
    }
  }, [state]);

  if (state.ok && state.data) {
    const created = state.data;
    return (
      <Card className="mx-auto max-w-2xl">
        <CardHeader className="items-start gap-3 sm:flex-row sm:items-center">
          <span className="flex size-11 shrink-0 items-center justify-center rounded-full bg-emerald-50 text-emerald-600">
            <CheckCircle2 className="size-6" aria-hidden />
          </span>
          <div>
            <CardTitle>Campanha criada</CardTitle>
            <CardDescription>
              <strong className="text-slate-700">{created.ballotName}</strong> está pronta. Entregue o acesso abaixo ao administrador da
              campanha.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <CredentialsPanel credentials={created.credentials} />
        </CardContent>
        <CardFooter className="flex-col-reverse items-stretch sm:flex-row sm:items-center">
          <Button variant="outline" onClick={onRestart}>
            <Plus aria-hidden /> Criar outra campanha
          </Button>
          <ButtonLink href={`/super/campanhas/${created.campaignId}`}>Abrir campanha</ButtonLink>
        </CardFooter>
      </Card>
    );
  }

  return (
    <form ref={formRef} onSubmit={onSubmit} noValidate className="mx-auto max-w-3xl space-y-6">
      <FormMessage result={state} />

      <Card>
        <CardHeader className="flex-row items-center gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
            <ShieldCheck className="size-5" aria-hidden />
          </span>
          <div>
            <CardTitle>Candidato e campanha</CardTitle>
            <CardDescription>Cada campanha é isolada: nenhum candidato enxerga os dados de outro.</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <CampaignFields errors={state.fieldErrors} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
            <UserCog className="size-5" aria-hidden />
          </span>
          <div>
            <CardTitle>Primeiro administrador</CardTitle>
            <CardDescription>Terá acesso total à campanha e cadastrará coordenadores e cabos eleitorais.</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <AccountFields errors={state.fieldErrors} prefix="admin" />
        </CardContent>
      </Card>

      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <ButtonLink href="/super/campanhas" variant="outline">
          Cancelar
        </ButtonLink>
        <Button type="submit" loading={pending}>
          {pending ? "Criando campanha..." : "Criar campanha"}
        </Button>
      </div>
    </form>
  );
}
