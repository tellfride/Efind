import { requirePermission } from "@/lib/auth";
import { ModulePlaceholder } from "@/components/layout/placeholder";

export default async function Page() {
  await requirePermission("whatsapp");
  return <ModulePlaceholder title="Conexão da API do WhatsApp" />;
}
