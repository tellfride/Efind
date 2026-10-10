import type { Metadata } from "next";
import { requireSuperAdmin } from "@/lib/auth";
import { PageHeader } from "@/components/ui/misc";
import { AccountsManager } from "@/components/super/accounts-manager";
import { listSuperUsers } from "@/server/super/queries";

export const metadata: Metadata = { title: "Super admins" };

export default async function SuperUsersPage() {
  const user = await requireSuperAdmin();
  const accounts = await listSuperUsers();

  return (
    <>
      <PageHeader
        title="Super admins"
        description="Contas com acesso à administração da plataforma. Mantenha apenas as pessoas estritamente necessárias."
      />
      <AccountsManager mode={{ kind: "super", currentUserId: user.id }} accounts={accounts} />
    </>
  );
}
