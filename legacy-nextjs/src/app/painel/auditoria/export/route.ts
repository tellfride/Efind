// Exportação CSV da trilha de auditoria (mesmos filtros e escopo da tela).
import { NextResponse, type NextRequest } from "next/server";
import { authorize } from "@/lib/auth";
import { audit } from "@/lib/audit";
import { toCsv } from "@/lib/utils";
import { auditExportFilename } from "@/server/settings/audit-filters";
import { AUDIT_CSV_COLUMNS, exportAuditRows, getAuditContext, parseFiltersFor } from "@/server/settings/audit-log";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const auth = await authorize("auditoria", "view");
  if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status });
  const { user } = auth;

  const context = await getAuditContext(user);
  const filters = parseFiltersFor(context, req.nextUrl.searchParams);
  const { rows, truncated } = await exportAuditRows(user, context, filters);

  await audit({
    action: "audit.export",
    campaignId: user.campaignId,
    userId: user.id,
    entity: "AuditLog",
    details: { count: rows.length, truncated, filters: { ...filters } },
  });

  const csv = toCsv(rows, AUDIT_CSV_COLUMNS);
  return new NextResponse(csv, {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="${auditExportFilename(filters)}"`,
      "Cache-Control": "no-store",
    },
  });
}
