import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ExternalLink, Info } from "lucide-react";
import { requirePermission } from "@/lib/auth";
import { can } from "@/lib/permissions";
import { CAMPAIGN_STATUS_LABELS, type CampaignStatus } from "@/lib/constants";
import { formatDate, formatDateTime } from "@/lib/utils";
import { Alert, Badge, Card, CardContent, CardHeader, CardTitle, PageHeader } from "@/components/ui";
import { SettingsEditor } from "@/components/settings/settings-editor";
import { getCampaignSettings } from "@/server/settings/campaign-settings";

export const metadata: Metadata = { title: "Configurações" };

export default async function ConfiguracoesPage() {
  const user = await requirePermission("configuracoes");
  const settings = await getCampaignSettings(user.campaignId);
  if (!settings) notFound();

  const canEdit = can(user.permissions, "configuracoes", "edit");
  const formHref = `/c/${user.inviteCode}`;
  const status = settings.status as CampaignStatus;

  const infoCard = (
    <Card>
      <CardHeader>
        <CardTitle>Dados da campanha</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="space-y-3 text-sm">
          <div className="flex items-center justify-between gap-3">
            <dt className="text-slate-500">Identificador</dt>
            <dd className="truncate font-mono text-slate-800">{settings.slug}</dd>
          </div>
          <div className="flex items-center justify-between gap-3">
            <dt className="text-slate-500">Situação</dt>
            <dd>
              <Badge tone={status === "ACTIVE" ? "green" : "red"}>{CAMPAIGN_STATUS_LABELS[status] ?? settings.status}</Badge>
            </dd>
          </div>
          <div className="flex items-center justify-between gap-3">
            <dt className="text-slate-500">Criada em</dt>
            <dd className="text-slate-800">{formatDate(settings.createdAt)}</dd>
          </div>
          <div className="flex items-center justify-between gap-3">
            <dt className="text-slate-500">Última alteração</dt>
            <dd className="text-slate-800">{formatDateTime(settings.updatedAt)}</dd>
          </div>
        </dl>
        <p className="mt-4 flex gap-2 rounded-lg bg-slate-50 p-3 text-xs text-slate-500">
          <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          Identificador e situação são definidos pelo suporte do E-Find. Para alterá-los, entre em contato pelo e-mail
          contato@efind.com.br.
        </p>
      </CardContent>
    </Card>
  );

  return (
    <>
      <PageHeader
        title="Configurações"
        description="Identidade visual, formulário público de cadastro e textos de consentimento da campanha."
        actions={
          <a
            href={formHref}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-10 items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
          >
            <ExternalLink className="size-4" aria-hidden /> Ver formulário público
          </a>
        }
      />
      {!canEdit && (
        <Alert tone="info" title="Somente leitura" className="mb-6">
          Você pode consultar as configurações, mas apenas quem tem permissão de edição pode alterá-las. Fale com o
          administrador da campanha se precisar mudar algo.
        </Alert>
      )}
      <SettingsEditor
        canEdit={canEdit}
        formHref={formHref}
        infoCard={infoCard}
        settings={{
          candidateName: settings.candidateName,
          ballotName: settings.ballotName,
          ballotNumber: settings.ballotNumber,
          party: settings.party,
          office: settings.office,
          city: settings.city,
          state: settings.state,
          electionYear: settings.electionYear,
          voterGoal: settings.voterGoal,
          primaryColor: settings.primaryColor,
          logoUrl: settings.logoUrl,
          formTitle: settings.formTitle,
          formMessage: settings.formMessage,
          formConfig: settings.formConfig,
          consentText: settings.consentText,
          privacyContact: settings.privacyContact,
        }}
      />
    </>
  );
}
