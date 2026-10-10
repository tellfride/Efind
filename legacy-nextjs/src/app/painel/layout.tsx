import { requireCampaignUser } from "@/lib/auth";
import { AppShell } from "@/components/layout/app-shell";

export const dynamic = "force-dynamic";

export default async function PainelLayout({ children }: { children: React.ReactNode }) {
  const user = await requireCampaignUser();
  return (
    <AppShell
      variant="panel"
      user={{ name: user.name, email: user.email, role: user.role, permissions: user.permissions }}
      campaign={{
        ballotName: user.campaign.ballotName,
        ballotNumber: user.campaign.ballotNumber,
        party: user.campaign.party,
        primaryColor: user.campaign.primaryColor,
        logoUrl: user.campaign.logoUrl,
      }}
    >
      {children}
    </AppShell>
  );
}
