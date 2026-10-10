import { requireSuperAdmin } from "@/lib/auth";
import { AppShell } from "@/components/layout/app-shell";

export const dynamic = "force-dynamic";

export default async function SuperLayout({ children }: { children: React.ReactNode }) {
  const user = await requireSuperAdmin();
  return (
    <AppShell variant="super" user={{ name: user.name, email: user.email, role: user.role, permissions: user.permissions }}>
      {children}
    </AppShell>
  );
}
