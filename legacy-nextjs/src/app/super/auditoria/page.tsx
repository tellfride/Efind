import { requireSuperAdmin } from "@/lib/auth";
import { ModulePlaceholder } from "@/components/layout/placeholder";

export default async function Page() {
  await requireSuperAdmin();
  return <ModulePlaceholder title="Auditoria" />;
}
