// Consultas de disparos/modelos usadas pelas páginas e ações (sempre limitadas à campanha do usuário).
import { prisma, type Prisma } from "@/lib/db";
import type { CampaignUser } from "@/lib/auth";
import { teamScopeWhere } from "@/server/access";
import type { FilterOption, VoterFilterOptions } from "@/server/filter-options";
import { getProviderDefinition } from "@/server/whatsapp/registry";
import type { VoterFilters } from "@/lib/voter-filters";
import { sendBlocker } from "./logic";

type ScopedUser = Pick<CampaignUser, "id" | "role" | "campaignId">;

/** Disparos visíveis: ADMIN vê todos da campanha; os demais, apenas os que criaram */
export function broadcastScopeWhere(user: ScopedUser): Prisma.BroadcastWhereInput {
  return user.role === "ADMIN" ? { campaignId: user.campaignId } : { campaignId: user.campaignId, createdById: user.id };
}

export async function findBroadcastInScope(user: ScopedUser, id: string) {
  return prisma.broadcast.findFirst({
    where: { AND: [broadcastScopeWhere(user), { id }] },
    include: { template: true, connection: true },
  });
}

/**
 * Pode (re)começar a enviar? Confere conexão, provedor e template aprovado.
 * Retorna a mensagem de erro para o usuário, ou null.
 */
export function broadcastSendProblem(b: {
  campaignId: string;
  connection: { status: string; campaignId: string; provider: string } | null;
  template: { providerTemplateName: string | null } | null;
}): string | null {
  const def = b.connection ? getProviderDefinition(b.connection.provider) : null;
  const blocker = sendBlocker({
    connection: b.connection,
    campaignId: b.campaignId,
    providerKnown: !!def,
    requiresApprovedTemplate: !!def?.requiresApprovedTemplate,
    template: b.template,
  });
  if (!blocker) return null;
  if (blocker.code === "template_required") {
    return "A conexão usa a API oficial, que exige template aprovado. Informe o nome do template aprovado no modelo antes de continuar.";
  }
  return `${blocker.message} Verifique em Conexão da API.`;
}

/**
 * Opções mínimas para exibir o resumo do público (nomes de quem cadastrou/coordenadores),
 * sem carregar todas as opções do painel de filtros.
 */
export async function summaryOptionsFor(user: ScopedUser, filters: VoterFilters): Promise<VoterFilterOptions> {
  const ids = [...(filters.registeredByIds ?? []), ...(filters.coordinatorIds ?? [])];
  const users = ids.length
    ? await prisma.user.findMany({ where: { campaignId: user.campaignId, id: { in: ids } }, select: { id: true, name: true } })
    : [];
  const members: FilterOption[] = users.map((u) => ({ value: u.id, label: u.name }));
  return { neighborhoods: [], cities: [], coordinators: members, members, tags: [], electoralZones: [] };
}

/** Os ids de equipe usados nos filtros pertencem à campanha e ao escopo do usuário? */
export async function filterIdsInScope(user: ScopedUser, filters: VoterFilters): Promise<boolean> {
  const ids = Array.from(new Set([...(filters.registeredByIds ?? []), ...(filters.coordinatorIds ?? [])]));
  if (!ids.length) return true;
  const found = await prisma.user.count({ where: { AND: [teamScopeWhere(user), { id: { in: ids } }] } });
  return found === ids.length;
}
