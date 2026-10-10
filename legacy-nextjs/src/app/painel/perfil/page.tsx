import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { CalendarClock, Link2, QrCode, ShieldCheck, UserRoundCheck } from "lucide-react";
import { requireCampaignUser } from "@/lib/auth";
import { prisma } from "@/lib/db";
import { can } from "@/lib/permissions";
import { OFFICE_LABELS, ROLE_LABELS, type Office, type Role } from "@/lib/constants";
import { registrationUrl } from "@/lib/qrcode";
import { formatDate, formatDateTime, formatNumber } from "@/lib/utils";
import { ChangePasswordForm, ProfileForm } from "@/components/account/account-forms";
import { Avatar, Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, CopyButton, PageHeader } from "@/components/ui";
import { buttonClasses } from "@/components/ui/button";

export const metadata: Metadata = { title: "Meu perfil" };

function parentLabel(role: Role): string {
  return role === "CABO" ? "Coordenador" : "Responsável";
}

export default async function PerfilPage() {
  const user = await requireCampaignUser();
  const [me, registered] = await Promise.all([
    prisma.user.findFirst({
      where: { id: user.id, campaignId: user.campaignId },
      select: {
        phone: true,
        createdAt: true,
        lastLoginAt: true,
        goal: true,
        region: true,
        parent: { select: { name: true, role: true } },
      },
    }),
    prisma.voter.count({ where: { campaignId: user.campaignId, registeredById: user.id } }),
  ]);
  if (!me) notFound();

  const link = registrationUrl(user.inviteCode);
  const canSeeLink = can(user.permissions, "meu_link", "view");
  const campaign = user.campaign;
  const campaignLine = [campaign.ballotNumber, campaign.party, OFFICE_LABELS[campaign.office as Office]].filter(Boolean).join(" · ");

  return (
    <>
      <PageHeader title="Meu perfil" description="Seus dados de acesso, senha e link pessoal de cadastro." />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-6">
          <ProfileForm name={user.name} email={user.email} phone={me.phone} />
          <ChangePasswordForm />
        </div>

        <aside className="min-w-0 space-y-6">
          <Card>
            <CardContent className="space-y-4 pt-5">
              <div className="flex items-center gap-3">
                <Avatar name={user.name} className="size-12 text-base" />
                <div className="min-w-0">
                  <p className="truncate font-semibold text-slate-900">{user.name}</p>
                  <p className="truncate text-sm text-slate-500">{user.email}</p>
                </div>
              </div>
              <dl className="space-y-3 border-t border-slate-100 pt-4 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-slate-500">Papel</dt>
                  <dd>
                    <Badge tone="brand">{ROLE_LABELS[user.role]}</Badge>
                  </dd>
                </div>
                <div className="flex items-start justify-between gap-3">
                  <dt className="shrink-0 text-slate-500">Campanha</dt>
                  <dd className="min-w-0 text-right">
                    <p className="truncate font-medium text-slate-800">{campaign.ballotName}</p>
                    {campaignLine && <p className="truncate text-xs text-slate-500">{campaignLine}</p>}
                  </dd>
                </div>
                {user.role !== "ADMIN" && (
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-slate-500">{parentLabel(user.role)}</dt>
                    <dd className="truncate text-slate-800">{me.parent?.name ?? "—"}</dd>
                  </div>
                )}
                {me.region && (
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-slate-500">Região de atuação</dt>
                    <dd className="truncate text-slate-800">{me.region}</dd>
                  </div>
                )}
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-slate-500">Cadastros realizados</dt>
                  <dd className="font-semibold text-slate-900 tabular-nums">
                    {formatNumber(registered)}
                    {me.goal ? <span className="font-normal text-slate-500"> de {formatNumber(me.goal)}</span> : null}
                  </dd>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-slate-500">Na equipe desde</dt>
                  <dd className="text-slate-800">{formatDate(me.createdAt)}</dd>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <dt className="flex items-center gap-1 text-slate-500">
                    <CalendarClock className="size-3.5" aria-hidden /> Último acesso
                  </dt>
                  <dd className="text-slate-800">{formatDateTime(me.lastLoginAt)}</dd>
                </div>
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Link2 className="size-4 text-brand-600" aria-hidden /> Meu link de cadastro
              </CardTitle>
              <CardDescription>Todo eleitor que se cadastrar por este link fica vinculado a você.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 font-mono text-xs break-all text-slate-700">
                {link}
              </p>
              <div className="flex flex-wrap gap-2">
                <CopyButton value={link} size="sm" label="Copiar link" />
                {canSeeLink && (
                  <Link href="/painel/meu-link" className={buttonClasses({ variant: "secondary", size: "sm" })}>
                    <QrCode aria-hidden /> QR Code e cartaz
                  </Link>
                )}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ShieldCheck className="size-4 text-brand-600" aria-hidden /> Meus dados e privacidade
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm text-slate-600">
              <p>
                Seu nome, e-mail e telefone são usados apenas para o acesso ao painel e a organização da campanha. A campanha é
                a controladora desses dados; o E-Find é o operador da plataforma.
              </p>
              <p className="flex gap-2">
                <UserRoundCheck className="mt-0.5 size-4 shrink-0 text-slate-400" aria-hidden />
                Logins, alterações e exportações feitas com a sua conta ficam registrados na trilha de auditoria da campanha.
              </p>
              <p>
                Para corrigir o e-mail de acesso, desativar a conta ou pedir a exclusão dos seus dados, fale com o administrador da
                campanha.
              </p>
              <p className="flex flex-wrap gap-x-4 gap-y-1 pt-1">
                <Link href="/privacidade" target="_blank" className="font-medium text-brand-600 hover:text-brand-700">
                  Política de privacidade
                </Link>
                <Link href="/termos" target="_blank" className="font-medium text-brand-600 hover:text-brand-700">
                  Termos de uso
                </Link>
              </p>
            </CardContent>
          </Card>
        </aside>
      </div>
    </>
  );
}
