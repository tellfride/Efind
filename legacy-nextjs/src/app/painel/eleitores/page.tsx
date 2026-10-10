import { requirePermission } from "@/lib/auth";
import { ModulePlaceholder } from "@/components/layout/placeholder";

export default async function Page() {
  await requirePermission("eleitores");
  return <ModulePlaceholder title="Eleitores" />;
}
