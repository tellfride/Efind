import { requireAdmin } from "@/lib/auth";
import { ModulePlaceholder } from "@/components/layout/placeholder";

export default async function Page() {
  await requireAdmin();
  return <ModulePlaceholder title="Permissões" />;
}
