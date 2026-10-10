// Inicialização de uma campanha nova: permissões padrão por papel + dashboards-modelo.
// Chamado pelo super admin ao criar a campanha e pelo seed.
import type { Prisma } from "@prisma/client";
import { CONFIGURABLE_ROLES } from "@/lib/constants";
import { MODULE_KEYS, defaultPermissionsFor } from "@/lib/permissions";
import { createDefaultDashboards } from "@/server/dashboard/presets";

export async function bootstrapCampaign(tx: Prisma.TransactionClient, campaignId: string): Promise<void> {
  for (const role of CONFIGURABLE_ROLES) {
    const perms = defaultPermissionsFor(role);
    await tx.rolePermission.createMany({
      data: MODULE_KEYS.map((module) => ({
        campaignId,
        role,
        module,
        canView: perms[module].view,
        canCreate: perms[module].create,
        canEdit: perms[module].edit,
        canDelete: perms[module].delete,
        canExport: perms[module].export,
      })),
    });
  }
  await createDefaultDashboards(tx, campaignId);
}
