import { requirePermission } from "@/lib/auth";
import { ModulePlaceholder } from "@/components/layout/placeholder";

export default async function Page() {
  await requirePermission("dashboard");
  return <ModulePlaceholder title="Início" />;
}
