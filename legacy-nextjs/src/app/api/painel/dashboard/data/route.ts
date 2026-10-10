// Dados dos widgets de dashboard: POST { widgets } → { [widgetId]: dados | { error } }
// Os dados são sempre calculados dentro da campanha e do escopo hierárquico do usuário logado.
import { NextResponse } from "next/server";
import { z } from "zod";
import { authorize } from "@/lib/auth";
import { dashboardWidgetsSchema } from "@/lib/dashboard-types";
import { computeDashboardData } from "@/server/dashboard/data";

export const dynamic = "force-dynamic";

const bodySchema = z.object({ widgets: dashboardWidgetsSchema });

const NO_STORE = { "Cache-Control": "no-store" };

export async function POST(request: Request) {
  const auth = await authorize("dashboard", "view");
  if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status, headers: NO_STORE });

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Requisição inválida." }, { status: 400, headers: NO_STORE });
  }
  const parsed = bodySchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.issues[0]?.message ?? "Widgets inválidos." },
      { status: 400, headers: NO_STORE },
    );
  }

  const data = await computeDashboardData(auth.user, parsed.data.widgets);
  return NextResponse.json(data, { headers: NO_STORE });
}
