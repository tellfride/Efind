import type { Metadata } from "next";
import Link from "next/link";
import { CalendarClock, Lock, PauseCircle, Plus, ShieldCheck, Users, UsersRound } from "lucide-react";
import { requireSuperAdmin } from "@/lib/auth";
import { ButtonLink } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, PageHeader, StatCard } from "@/components/ui/misc";
import { CampaignTable } from "@/components/super/campaign-display";
import { getPlatformOverview } from "@/server/super/queries";
import { firstName, formatNumber } from "@/lib/utils";

export const metadata: Metadata = { title: "Visão geral" };

export default async function SuperOverviewPage() {
  const user = await requireSuperAdmin();
  const overview = await getPlatformOverview(8);

  return (
    <>
      <PageHeader
        title="Visão geral da plataforma"
        description={`Olá, ${firstName(user.name)}. Acompanhe as campanhas e o crescimento do E-Find.`}
        actions={
          <ButtonLink href="/super/campanhas/nova">
            <Plus aria-hidden /> Nova campanha
          </ButtonLink>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <StatCard label="Campanhas ativas" value={formatNumber(overview.active)} icon={ShieldCheck} tone="green" />
        <StatCard
          label="Campanhas suspensas"
          value={formatNumber(overview.suspended)}
          icon={PauseCircle}
          tone={overview.suspended > 0 ? "red" : "gray"}
        />
        <StatCard label="Usuários de campanhas" value={formatNumber(overview.campaignUsers)} hint="Administradores, coordenadores e cabos" icon={Users} tone="blue" />
        <StatCard label="Eleitores cadastrados" value={formatNumber(overview.voters)} hint="Em todas as campanhas" icon={UsersRound} />
        <StatCard label="Cadastros em 7 dias" value={formatNumber(overview.votersLast7)} hint="Novos eleitores na última semana" icon={CalendarClock} tone="purple" />
      </div>

      <Card className="mt-6">
        <CardHeader className="gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle>Campanhas recentes</CardTitle>
            <CardDescription>As últimas campanhas criadas na plataforma</CardDescription>
          </div>
          {overview.totalCampaigns > 0 && (
            <Link href="/super/campanhas" className="text-sm font-medium text-brand-700 hover:underline">
              Ver todas ({formatNumber(overview.totalCampaigns)})
            </Link>
          )}
        </CardHeader>
        {overview.totalCampaigns === 0 ? (
          <EmptyState
            icon={ShieldCheck}
            title="Nenhuma campanha ainda"
            description="Crie a primeira campanha para entregar o acesso ao administrador do candidato."
            action={
              <ButtonLink href="/super/campanhas/nova">
                <Plus aria-hidden /> Nova campanha
              </ButtonLink>
            }
          />
        ) : (
          <CampaignTable campaigns={overview.recent} emptyMessage="Nenhuma campanha cadastrada." />
        )}
      </Card>

      <p className="mt-4 flex items-start gap-2 text-xs text-slate-500">
        <Lock className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        O super admin vê apenas números agregados das campanhas. Dados pessoais de eleitores ficam restritos a cada campanha (LGPD).
      </p>
    </>
  );
}
