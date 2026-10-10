import { redirect } from "next/navigation";
import { getSessionUser, homePathFor } from "@/lib/auth";

// Página inicial provisória: o módulo "settings" substitui por uma landing page pública.
export default async function Home() {
  const user = await getSessionUser();
  redirect(user ? homePathFor(user.role) : "/login");
}
