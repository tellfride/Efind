"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { KeyRound, Mail, Phone, Power, PowerOff, UserPlus, Users } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { FormMessage } from "@/components/ui/form";
import { Modal } from "@/components/ui/client";
import { Avatar, EmptyState } from "@/components/ui/misc";
import type { ActionResult } from "@/lib/action-result";
import { formatPhone } from "@/lib/phone";
import { formatDateTime } from "@/lib/utils";
import {
  createCampaignAdminAction,
  resetCampaignAdminPasswordAction,
  setCampaignAdminActiveAction,
} from "@/server/super/campaign-actions";
import { createSuperUserAction, resetSuperUserPasswordAction, setSuperUserActiveAction } from "@/server/super/user-actions";
import type { IssuedCredentials } from "@/server/super/validation";
import { AccountFields } from "./account-fields";
import { CredentialsPanel } from "./credentials-panel";
import { useActionForm } from "./use-action-form";

export interface AccountItem {
  id: string;
  name: string;
  email: string;
  phone: string | null;
  active: boolean;
  lastLoginAt: Date | null;
  createdAt: Date;
}

/** Administradores de uma campanha ou super admins da plataforma */
export type AccountsMode = { kind: "campaign-admin"; campaignId: string } | { kind: "super"; currentUserId: string };

type Pending = { type: "reset" | "toggle"; account: AccountItem } | null;

const COPY = {
  "campaign-admin": {
    title: "Administradores",
    description: "Acesso total à campanha. Somente o super admin cria administradores.",
    add: "Adicionar administrador",
    addTitle: "Novo administrador da campanha",
    emptyTitle: "Nenhum administrador",
    emptyDescription: "Adicione um administrador para que a campanha possa ser gerenciada.",
  },
  super: {
    title: "Super admins",
    description: "Donos da plataforma: criam e gerenciam campanhas. Não veem dados pessoais de eleitores.",
    add: "Novo super admin",
    addTitle: "Novo super admin",
    emptyTitle: "Nenhum super admin",
    emptyDescription: "Crie outro super admin para dividir a gestão da plataforma.",
  },
} as const;

export function AccountsManager({ mode, accounts }: { mode: AccountsMode; accounts: AccountItem[] }) {
  const router = useRouter();
  const copy = COPY[mode.kind];
  const [createRound, setCreateRound] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [confirming, setConfirming] = useState<Pending>(null);
  const [credentials, setCredentials] = useState<IssuedCredentials | null>(null);
  const [pending, startTransition] = useTransition();

  const isSelf = (a: AccountItem) => mode.kind === "super" && a.id === mode.currentUserId;
  const activeCount = accounts.filter((a) => a.active).length;

  const openCreate = () => {
    setCreateRound((r) => r + 1);
    setCreateOpen(true);
  };

  const runConfirmed = () => {
    if (!confirming) return;
    const { type, account } = confirming;
    startTransition(async () => {
      let res: ActionResult<IssuedCredentials> | ActionResult;
      if (type === "reset") {
        res =
          mode.kind === "campaign-admin"
            ? await resetCampaignAdminPasswordAction({ campaignId: mode.campaignId, userId: account.id })
            : await resetSuperUserPasswordAction({ userId: account.id });
      } else {
        const active = !account.active;
        res =
          mode.kind === "campaign-admin"
            ? await setCampaignAdminActiveAction({ campaignId: mode.campaignId, userId: account.id, active })
            : await setSuperUserActiveAction({ userId: account.id, active });
      }
      if (!res.ok) {
        toast.error(res.error ?? "Não foi possível concluir a ação");
        return;
      }
      toast.success(res.message ?? "Pronto");
      setConfirming(null);
      if (type === "reset" && res.data) setCredentials(res.data as IssuedCredentials);
      router.refresh();
    });
  };

  return (
    <Card>
      <CardHeader className="gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <CardTitle>{copy.title}</CardTitle>
          <CardDescription>{copy.description}</CardDescription>
        </div>
        <Button onClick={openCreate} className="self-start sm:self-auto">
          <UserPlus aria-hidden /> {copy.add}
        </Button>
      </CardHeader>

      {accounts.length === 0 ? (
        <EmptyState icon={Users} title={copy.emptyTitle} description={copy.emptyDescription} />
      ) : (
        <ul className="divide-y divide-slate-100">
          {accounts.map((a) => {
            const self = isSelf(a);
            const lastActive = a.active && activeCount <= 1;
            return (
              <li key={a.id} className="flex flex-col gap-3 px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
                <div className="flex min-w-0 items-start gap-3">
                  <Avatar name={a.name} className="size-10" />
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="truncate font-medium text-slate-900">{a.name}</p>
                      {self && <Badge tone="brand">Você</Badge>}
                      {a.active ? <Badge tone="green">Ativo</Badge> : <Badge tone="gray">Desativado</Badge>}
                    </div>
                    <p className="mt-0.5 flex items-center gap-1.5 truncate text-sm text-slate-600">
                      <Mail className="size-3.5 shrink-0 text-slate-400" aria-hidden /> <span className="truncate">{a.email}</span>
                    </p>
                    {a.phone && (
                      <p className="flex items-center gap-1.5 text-sm text-slate-600">
                        <Phone className="size-3.5 shrink-0 text-slate-400" aria-hidden /> {formatPhone(a.phone)}
                      </p>
                    )}
                    <p className="mt-1 text-xs text-slate-500">
                      {a.lastLoginAt ? `Último acesso: ${formatDateTime(a.lastLoginAt)}` : "Ainda não acessou"} · Criado em{" "}
                      {formatDateTime(a.createdAt)}
                    </p>
                  </div>
                </div>

                <div className="flex flex-wrap gap-2 lg:shrink-0 lg:justify-end">
                  {self ? (
                    <Link href="/super/perfil" className="text-sm font-medium text-brand-700 hover:underline">
                      Alterar minha senha em Meu perfil
                    </Link>
                  ) : (
                    <>
                      <Button variant="outline" size="sm" onClick={() => setConfirming({ type: "reset", account: a })} disabled={!a.active}>
                        <KeyRound aria-hidden /> Redefinir senha
                      </Button>
                      {a.active ? (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setConfirming({ type: "toggle", account: a })}
                          disabled={lastActive}
                          title={lastActive ? "É preciso manter pelo menos um usuário ativo" : undefined}
                        >
                          <PowerOff aria-hidden /> Desativar
                        </Button>
                      ) : (
                        <Button variant="outline" size="sm" onClick={() => setConfirming({ type: "toggle", account: a })}>
                          <Power aria-hidden /> Reativar
                        </Button>
                      )}
                    </>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {/* Confirmação de redefinição de senha / ativação */}
      <Modal
        open={!!confirming}
        onClose={() => !pending && setConfirming(null)}
        title={
          confirming?.type === "reset"
            ? "Redefinir senha?"
            : confirming?.account.active
              ? "Desativar acesso?"
              : "Reativar acesso?"
        }
        description={confirming ? `${confirming.account.name} · ${confirming.account.email}` : undefined}
        size="sm"
        footer={
          <>
            <Button variant="outline" onClick={() => setConfirming(null)} disabled={pending}>
              Cancelar
            </Button>
            <Button
              variant={confirming?.type === "toggle" && confirming.account.active ? "danger" : "primary"}
              onClick={runConfirmed}
              loading={pending}
            >
              {confirming?.type === "reset" ? "Gerar nova senha" : confirming?.account.active ? "Desativar" : "Reativar"}
            </Button>
          </>
        }
      >
        <p className="text-sm text-slate-600">
          {confirming?.type === "reset"
            ? "Uma senha provisória será gerada e exibida uma única vez. A senha atual deixa de funcionar e as sessões abertas são encerradas."
            : confirming?.account.active
              ? "O usuário não conseguirá mais entrar e as sessões abertas são encerradas. Os dados continuam preservados."
              : "O usuário volta a conseguir entrar com a senha atual."}
        </p>
      </Modal>

      {/* Credenciais geradas na redefinição */}
      <Modal
        open={!!credentials}
        onClose={() => setCredentials(null)}
        title="Nova senha gerada"
        description={credentials?.name}
        footer={<Button onClick={() => setCredentials(null)}>Concluir</Button>}
      >
        {credentials && <CredentialsPanel credentials={credentials} />}
      </Modal>

      {/* Criação */}
      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title={copy.addTitle} size="lg">
        <CreateAccountForm
          key={createRound}
          mode={mode}
          onDone={() => setCreateOpen(false)}
          onCreated={() => router.refresh()}
        />
      </Modal>
    </Card>
  );
}

function CreateAccountForm({ mode, onDone, onCreated }: { mode: AccountsMode; onDone: () => void; onCreated: () => void }) {
  const action = mode.kind === "campaign-admin" ? createCampaignAdminAction : createSuperUserAction;
  const { state, onSubmit, pending } = useActionForm<IssuedCredentials>(action);
  // Ref evita repetir o efeito quando o pai recria o callback a cada renderização
  const onCreatedRef = useRef(onCreated);
  useEffect(() => {
    onCreatedRef.current = onCreated;
  });

  useEffect(() => {
    if (state.ok) {
      toast.success(state.message ?? "Usuário criado");
      onCreatedRef.current();
    }
  }, [state]);

  if (state.ok && state.data) {
    return (
      <div className="space-y-4">
        <CredentialsPanel credentials={state.data} />
        <div className="flex justify-end">
          <Button onClick={onDone}>Concluir</Button>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      {!state.ok && <FormMessage result={state} />}
      {mode.kind === "campaign-admin" && <input type="hidden" name="campaignId" value={mode.campaignId} />}
      <AccountFields errors={state.fieldErrors} autoFocus />
      <div className="flex flex-col-reverse gap-2 border-t border-slate-100 pt-4 sm:flex-row sm:justify-end">
        <Button variant="outline" onClick={onDone} disabled={pending}>
          Cancelar
        </Button>
        <Button type="submit" loading={pending}>
          {pending ? "Criando..." : "Criar acesso"}
        </Button>
      </div>
    </form>
  );
}
