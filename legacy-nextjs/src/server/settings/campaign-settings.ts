// Leitura das configurações da campanha para a tela /painel/configuracoes (servidor).
import { prisma } from "@/lib/db";
import { parseFormConfig, type FormConfig, type Office, type UF } from "@/lib/constants";

export interface CampaignSettings {
  id: string;
  slug: string;
  status: string;
  createdAt: Date;
  updatedAt: Date;
  candidateName: string;
  ballotName: string;
  ballotNumber: string | null;
  party: string | null;
  office: Office;
  city: string | null;
  state: UF | null;
  electionYear: number;
  voterGoal: number | null;
  primaryColor: string;
  logoUrl: string | null;
  formTitle: string | null;
  formMessage: string | null;
  formConfig: FormConfig;
  consentText: string | null;
  privacyContact: string | null;
}

export async function getCampaignSettings(campaignId: string): Promise<CampaignSettings | null> {
  const c = await prisma.campaign.findUnique({ where: { id: campaignId } });
  if (!c) return null;
  return {
    id: c.id,
    slug: c.slug,
    status: c.status,
    createdAt: c.createdAt,
    updatedAt: c.updatedAt,
    candidateName: c.candidateName,
    ballotName: c.ballotName,
    ballotNumber: c.ballotNumber,
    party: c.party,
    office: c.office as Office,
    city: c.city,
    state: (c.state as UF | null) ?? null,
    electionYear: c.electionYear,
    voterGoal: c.voterGoal,
    primaryColor: c.primaryColor,
    logoUrl: c.logoUrl,
    formTitle: c.formTitle,
    formMessage: c.formMessage,
    formConfig: parseFormConfig(c.formConfig),
    consentText: c.consentText,
    privacyContact: c.privacyContact,
  };
}
