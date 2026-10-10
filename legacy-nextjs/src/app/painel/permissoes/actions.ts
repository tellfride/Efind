"use server";

// Matriz de permissões — exclusiva do ADMIN da campanha (authorize("admin")).
import { revalidatePath } from "next/cache";
import { z } from "zod";
import { prisma } from "@/lib/db";
import { authorize } from "@/lib/auth";
import { audit } from "@/lib/audit";
import { actionError, actionOk, type ActionResult } from "@/lib/action-result";
import { CONFIGURABLE_ROLES } from "@/lib/constants";
import { MODULE_KEYS, type PermissionSet } from "@/lib/permissions";
import {
  describeChange,
  diffMatrices,
  diffOverrides,
  matrixToRows,
  normalizeMatrix,
  normalizeOverrides,
  overridesFromRows,
  roleMatrixFromRows,
  serializeOverrides,
  type OverrideMatrix,
} from "@/components/team/permission-logic";

// Estrutura aceita: { [módulo]: { [ação]: boolean } } — valores fora do contrato são descartados na normalização
const cellsSchema = z.record(z.string().max(40), z.record(z.string().max(20), z.boolean().nullable()));

const roleSchema = z.object({
  role: z.enum(CONFIGURABLE_ROLES),
  matrix: cellsSchema,
});

const MAX_AUDIT_CHANGES = 60;

export async function saveRolePermissionsAction(input: unknown): Promise<ActionResult<{ matrix: PermissionSet }>> {
  const auth = await authorize("admin");
  if (!auth.ok) return actionError(auth.error);
  const me = auth.user;

  const parsed = roleSchema.safeParse(input);
  if (!parsed.success) return actionError("Dados de permissão inválidos.");
  const { role } = parsed.data;
  const next = normalizeMatrix(parsed.data.matrix);

  const currentRows = await prisma.rolePermission.findMany({ where: { campaignId: me.campaignId, role } });
  const before = roleMatrixFromRows(role, currentRows);
  const changes = diffMatrices(before, next);

  await prisma.$transaction(
    matrixToRows(next).map((row) =>
      prisma.rolePermission.upsert({
        where: { campaignId_role_module: { campaignId: me.campaignId, role, module: row.module } },
        create: {
          campaignId: me.campaignId,
          role,
          module: row.module,
          canView: !!row.canView,
          canCreate: !!row.canCreate,
          canEdit: !!row.canEdit,
          canDelete: !!row.canDelete,
          canExport: !!row.canExport,
        },
        update: {
          canView: !!row.canView,
          canCreate: !!row.canCreate,
          canEdit: !!row.canEdit,
          canDelete: !!row.canDelete,
          canExport: !!row.canExport,
        },
      }),
    ),
  );

  if (changes.length) {
    await audit({
      action: "permissions.update",
      campaignId: me.campaignId,
      userId: me.id,
      entity: "RolePermission",
      entityId: role,
      details: {
        scope: "role",
        role,
        totalChanges: changes.length,
        changes: changes.slice(0, MAX_AUDIT_CHANGES).map(describeChange),
      },
    });
  }
  revalidatePath("/painel/permissoes");
  return actionOk(changes.length ? "Permissões salvas. Elas já valem nos próximos acessos da equipe." : "Nenhuma alteração para salvar.", {
    matrix: next,
  });
}

const overridesSchema = z.object({
  userId: z.string().trim().min(1).max(64),
  overrides: cellsSchema,
});

export async function saveUserOverridesAction(input: unknown): Promise<ActionResult<{ overrides: OverrideMatrix }>> {
  const auth = await authorize("admin");
  if (!auth.ok) return actionError(auth.error);
  const me = auth.user;

  const parsed = overridesSchema.safeParse(input);
  if (!parsed.success) return actionError("Dados de permissão inválidos.");

  // Apenas coordenadores e cabos da própria campanha têm exceções
  const target = await prisma.user.findFirst({
    where: { id: parsed.data.userId, campaignId: me.campaignId, role: { in: ["COORDENADOR", "CABO"] } },
    select: { id: true, role: true, permissions: true },
  });
  if (!target) return actionError("Usuário não encontrado.");
  const role = target.role as (typeof CONFIGURABLE_ROLES)[number];

  const roleRows = await prisma.rolePermission.findMany({ where: { campaignId: me.campaignId, role } });
  const inherited = roleMatrixFromRows(role, roleRows);
  const next = normalizeOverrides(parsed.data.overrides, inherited);
  const before = overridesFromRows(target.permissions);
  const changes = diffOverrides(before, next);
  const { upserts, deletes } = serializeOverrides(next);

  await prisma.$transaction([
    // Linhas totalmente "herdar" (e módulos que não existem mais) são removidas
    prisma.userPermission.deleteMany({
      where: { userId: target.id, OR: [{ module: { in: deletes } }, { module: { notIn: MODULE_KEYS } }] },
    }),
    ...upserts.map((row) =>
      prisma.userPermission.upsert({
        where: { userId_module: { userId: target.id, module: row.module } },
        create: { userId: target.id, ...row },
        update: {
          canView: row.canView,
          canCreate: row.canCreate,
          canEdit: row.canEdit,
          canDelete: row.canDelete,
          canExport: row.canExport,
        },
      }),
    ),
  ]);

  if (changes.length) {
    await audit({
      action: "permissions.update",
      campaignId: me.campaignId,
      userId: me.id,
      entity: "UserPermission",
      entityId: target.id,
      details: {
        scope: "user",
        role,
        totalChanges: changes.length,
        changes: changes.slice(0, MAX_AUDIT_CHANGES).map(describeChange),
      },
    });
  }
  revalidatePath("/painel/permissoes");
  return actionOk(changes.length ? "Exceções salvas." : "Nenhuma alteração para salvar.", { overrides: next });
}
