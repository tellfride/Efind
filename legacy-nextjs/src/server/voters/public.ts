// Dados públicos do link de cadastro (/c/[code]). Expõe apenas o necessário para a página:
// identidade visual da campanha e o primeiro nome de quem indicou.
import { cache } from "react";
import { prisma } from "@/lib/db";
import { OFFICE_LABELS, type Office } from "@/lib/constants";
import { firstName } from "@/lib/utils";
import { isValidInviteCode, safeHexColor } from "@/components/voters/voter-utils";

export interface PublicCampaign {
  id: string;
  candidateName: string;
  ballotName: string;
  ballotNumber: string | null;
  party: string | null;
  officeLabel: string;
  city: string | null;
  state: string | null;
  logoUrl: string | null;
  primaryColor: string;
  formTitle: string | null;
  formMessage: string | null;
  formConfig: unknown;
  consentText: string | null;
  privacyContact: string | null;
}

export interface PublicRegistration {
  code: string;
  owner: { id: string; firstName: string };
  campaign: PublicCampaign;
}

/** Aceita apenas logos http(s) ou caminhos locais (evita javascript:/data: no src) */
function safeLogoUrl(url: string | null): string | null {
  if (!url) return null;
  const u = url.trim();
  return /^https?:\/\//i.test(u) || (u.startsWith("/") && !u.startsWith("//")) ? u : null;
}

/** Usuário ativo dono do código + campanha ativa; null caso contrário. Memoizado por requisição. */
export const getPublicRegistration = cache(async (code: string): Promise<PublicRegistration | null> => {
  if (!isValidInviteCode(code)) return null;
  const user = await prisma.user.findUnique({
    where: { inviteCode: code },
    select: {
      id: true,
      name: true,
      active: true,
      role: true,
      campaign: {
        select: {
          id: true,
          status: true,
          candidateName: true,
          ballotName: true,
          ballotNumber: true,
          party: true,
          office: true,
          city: true,
          state: true,
          logoUrl: true,
          primaryColor: true,
          formTitle: true,
          formMessage: true,
          formConfig: true,
          consentText: true,
          privacyContact: true,
        },
      },
    },
  });
  if (!user || !user.active || user.role === "SUPER_ADMIN" || !user.campaign || user.campaign.status !== "ACTIVE") {
    return null;
  }
  const c = user.campaign;
  return {
    code,
    owner: { id: user.id, firstName: firstName(user.name) },
    campaign: {
      id: c.id,
      candidateName: c.candidateName,
      ballotName: c.ballotName,
      ballotNumber: c.ballotNumber,
      party: c.party,
      officeLabel: OFFICE_LABELS[c.office as Office] ?? c.office,
      city: c.city,
      state: c.state,
      logoUrl: safeLogoUrl(c.logoUrl),
      primaryColor: safeHexColor(c.primaryColor),
      formTitle: c.formTitle,
      formMessage: c.formMessage,
      formConfig: c.formConfig,
      consentText: c.consentText,
      privacyContact: c.privacyContact,
    },
  };
});
