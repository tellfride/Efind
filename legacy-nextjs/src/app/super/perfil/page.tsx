import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { requireSuperAdmin } from "@/lib/auth";
import { PageHeader } from "@/components/ui/misc";
import { ChangePasswordForm, ProfileForm } from "@/components/account/account-forms";
import { getOwnProfile } from "@/server/super/queries";

export const metadata: Metadata = { title: "Meu perfil" };

export default async function SuperProfilePage() {
  const user = await requireSuperAdmin();
  const profile = await getOwnProfile(user.id);
  if (!profile) redirect("/login");

  return (
    <>
      <PageHeader title="Meu perfil" description="Seus dados e sua senha de acesso como super admin." />
      <div className="grid gap-6 lg:grid-cols-2">
        <ProfileForm name={profile.name} email={profile.email} phone={profile.phone} />
        <ChangePasswordForm />
      </div>
    </>
  );
}
