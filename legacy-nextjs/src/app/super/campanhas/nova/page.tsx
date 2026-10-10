import type { Metadata } from "next";
import { requireSuperAdmin } from "@/lib/auth";
import { PageHeader } from "@/components/ui/misc";
import { BackLink } from "@/components/super/campaign-display";
import { CampaignCreateWizard } from "@/components/super/campaign-create-form";

export const metadata: Metadata = { title: "Nova campanha" };

export default async function NewCampaignPage() {
  await requireSuperAdmin();
  return (
    <div className="mx-auto max-w-3xl">
      <BackLink href="/super/campanhas">Campanhas</BackLink>
      <PageHeader
        title="Nova campanha"
        description="Cadastre o candidato e o primeiro administrador. Permissões padrão por papel e dashboards-modelo são criados automaticamente."
      />
      <CampaignCreateWizard />
    </div>
  );
}
