import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { CalendarDays, Hash, Landmark, MapPin, UserRound } from "lucide-react";
import { requireSuperAdmin } from "@/lib/auth";
import { Alert, PageHeader } from "@/components/ui/misc";
import {
  BackLink,
  CampaignMark,
  CampaignStatusBadge,
  LinkTabs,
  officeLabel,
  placeLabel,
} from "@/components/super/campaign-display";
import { CampaignDangerZone, CampaignEditForm, CampaignStatusControl } from "@/components/super/campaign-manage";
import { AccountsManager } from "@/components/super/accounts-manager";
import { CampaignUsagePanel } from "@/components/super/campaign-usage";
import { formatDate } from "@/lib/utils";
import { getCampaignAdmins, getCampaignById, getCampaignUsage } from "@/server/super/queries";

export const metadata: Metadata = { title: "Campanha" };

const TABS = [
  { value: "dados", label: "Dados" },
  { value: "administradores", label: "Administradores" },
  { value: "uso", label: "Uso" },
] as const;
type TabValue = (typeof TABS)[number]["value"];

export default async function CampaignDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ tab?: string | string[] }>;
}) {
  await requireSuperAdmin();
  const { id } = await params;
  const sp = await searchParams;
  const rawTab = Array.isArray(sp.tab) ? sp.tab[0] : sp.tab;
  const tab: TabValue = TABS.some((t) => t.value === rawTab) ? (rawTab as TabValue) : "dados";

  const campaign = await getCampaignById(id);
  if (!campaign) notFound();

  const [admins, usage] = await Promise.all([
    tab === "administradores" ? getCampaignAdmins(campaign.id) : Promise.resolve(null),
    tab === "uso" ? getCampaignUsage(campaign.id) : Promise.resolve(null),
  ]);

  const basePath = `/super/campanhas/${campaign.id}`;
  const facts = [
    { icon: UserRound, text: campaign.candidateName },
    {
      icon: Landmark,
      text: [officeLabel(campaign.office), campaign.ballotNumber && `nº ${campaign.ballotNumber}`, campaign.party].filter(Boolean).join(" · "),
    },
    { icon: MapPin, text: placeLabel(campaign.city, campaign.state) },
    { icon: CalendarDays, text: `Eleição ${campaign.electionYear} · criada em ${formatDate(campaign.createdAt)}` },
    { icon: Hash, text: `Identificador: ${campaign.slug}` },
  ];

  return (
    <>
      <BackLink href="/super/campanhas">Campanhas</BackLink>
      <PageHeader
        title={
          <span className="flex items-center gap-3">
            <CampaignMark
              ballotName={campaign.ballotName}
              ballotNumber={campaign.ballotNumber}
              color={campaign.primaryColor}
              className="size-11"
            />
            <span className="min-w-0">
              <span className="block truncate">{campaign.ballotName}</span>
            </span>
            <CampaignStatusBadge status={campaign.status} className="shrink-0 align-middle" />
          </span>
        }
        description={
          <span className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5">
            {facts.map(({ icon: Icon, text }, i) => (
              <span key={i} className="inline-flex items-center gap-1.5">
                <Icon className="size-4 shrink-0 text-slate-400" aria-hidden /> {text}
              </span>
            ))}
          </span>
        }
        actions={<CampaignStatusControl campaignId={campaign.id} ballotName={campaign.ballotName} status={campaign.status} />}
      />

      {campaign.status === "SUSPENDED" && (
        <Alert tone="warning" title="Campanha suspensa" className="mb-6">
          A equipe desta campanha não consegue entrar no painel. Reative a campanha para liberar o acesso.
        </Alert>
      )}

      <LinkTabs
        className="mb-6"
        active={tab}
        tabs={TABS.map((t) => ({ value: t.value, label: t.label, href: t.value === "dados" ? basePath : `${basePath}?tab=${t.value}` }))}
      />

      {tab === "dados" && (
        <div className="space-y-6">
          <CampaignEditForm
            campaignId={campaign.id}
            values={{
              candidateName: campaign.candidateName,
              ballotName: campaign.ballotName,
              ballotNumber: campaign.ballotNumber,
              party: campaign.party,
              office: campaign.office,
              city: campaign.city,
              state: campaign.state,
              electionYear: campaign.electionYear,
              primaryColor: campaign.primaryColor,
              voterGoal: campaign.voterGoal,
            }}
          />
          <CampaignDangerZone campaignId={campaign.id} slug={campaign.slug} ballotName={campaign.ballotName} />
        </div>
      )}

      {tab === "administradores" && admins && (
        <AccountsManager mode={{ kind: "campaign-admin", campaignId: campaign.id }} accounts={admins} />
      )}

      {tab === "uso" && usage && <CampaignUsagePanel usage={usage} voterGoal={campaign.voterGoal} />}
    </>
  );
}
