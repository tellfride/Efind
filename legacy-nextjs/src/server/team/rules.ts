// Regras puras da equipe (sem banco): posição na hierarquia, quem gerencia quem e travas de segurança.
// As Server Actions carregam os dados do banco (sempre limitados à campanha/escopo) e decidem aqui.
import { CAMPAIGN_ROLES, ROLE_LABELS, type CampaignRole } from "@/lib/constants";

export interface TeamActor {
  id: string;
  role: CampaignRole;
}

/** Membro alvo de uma operação (já carregado dentro da campanha do ator) */
export interface TeamTarget {
  id: string;
  role: string;
  parentId: string | null;
  active: boolean;
}

/** Possível superior (já carregado dentro da campanha do ator) */
export interface ParentCandidate {
  id: string;
  role: string;
  active: boolean;
}

export type PlacementResult =
  | { ok: true; role: CampaignRole; parentId: string | null }
  | { ok: false; error: string; field: "role" | "parentId" | null };

export function isCampaignRole(value: unknown): value is CampaignRole {
  return typeof value === "string" && (CAMPAIGN_ROLES as readonly string[]).includes(value);
}

function fail(error: string, field: "role" | "parentId" | null): PlacementResult {
  return { ok: false, error, field };
}

/**
 * Superior sugerido quando o formulário não informa:
 *  - coordenador cadastrando → ele mesmo;
 *  - admin cadastrando coordenador → o próprio admin;
 *  - admin cadastrando cabo → o próprio admin apenas se não houver coordenadores ativos.
 */
export function defaultParentId(actor: TeamActor, role: CampaignRole, hasActiveCoordinators: boolean): string | null {
  if (role === "ADMIN") return null;
  if (actor.role === "COORDENADOR") return actor.id;
  if (role === "COORDENADOR") return actor.id;
  return hasActiveCoordinators ? null : actor.id;
}

/**
 * Define papel e superior de um membro novo (ou editado, quando `target` é informado).
 *  - CABO não cadastra ninguém.
 *  - COORDENADOR só cadastra CABO, sempre abaixo de si (o superior enviado é ignorado).
 *  - ADMIN: ADMIN não tem superior; COORDENADOR fica abaixo de um ADMIN ativo; CABO abaixo de um
 *    COORDENADOR ativo — ou de um ADMIN quando a campanha não tem coordenadores ativos.
 *  - Na edição, manter o mesmo superior (e o mesmo papel) é sempre aceito, mesmo que ele esteja inativo.
 * `candidates` deve conter apenas usuários da campanha do ator.
 */
export function resolvePlacement(input: {
  actor: TeamActor;
  requestedRole?: string | null;
  requestedParentId?: string | null;
  candidates: ParentCandidate[];
  hasActiveCoordinators: boolean;
  target?: Pick<TeamTarget, "id" | "role" | "parentId">;
}): PlacementResult {
  const { actor, candidates, hasActiveCoordinators, target } = input;

  if (actor.role === "CABO") return fail("Cabos eleitorais não podem cadastrar nem reposicionar membros da equipe.", null);

  if (actor.role === "COORDENADOR") {
    if (input.requestedRole && input.requestedRole !== "CABO") {
      return fail("Coordenadores só podem cadastrar cabos eleitorais.", "role");
    }
    if (target && (target.role !== "CABO" || target.parentId !== actor.id)) {
      return fail("Você só pode gerenciar os cabos eleitorais da sua equipe.", null);
    }
    return { ok: true, role: "CABO", parentId: actor.id };
  }

  if (actor.role !== "ADMIN") return fail("Você não pode gerenciar a equipe.", null);

  const role = input.requestedRole || target?.role;
  if (!isCampaignRole(role)) return fail("Escolha um papel válido.", "role");
  if (role === "ADMIN") return { ok: true, role, parentId: null };

  const parentId =
    input.requestedParentId ||
    (target && target.role === role ? target.parentId : null) ||
    defaultParentId(actor, role, hasActiveCoordinators);
  if (!parentId) {
    return fail(role === "CABO" ? "Escolha o coordenador responsável." : "Escolha o administrador responsável.", "parentId");
  }
  if (target && parentId === target.id) return fail("Um membro não pode ser o próprio responsável.", "parentId");

  const parent = candidates.find((c) => c.id === parentId);
  if (!parent) return fail("Responsável inválido.", "parentId");

  const unchanged = !!target && target.parentId === parentId && target.role === role;
  if (!parent.active && !unchanged) return fail("O responsável escolhido está inativo.", "parentId");

  if (role === "COORDENADOR") {
    if (parent.role !== "ADMIN") return fail("O coordenador deve ficar abaixo de um administrador.", "parentId");
    return { ok: true, role, parentId };
  }

  // CABO
  if (parent.role === "COORDENADOR") return { ok: true, role, parentId };
  if (parent.role === "ADMIN") {
    if (hasActiveCoordinators && !unchanged) {
      return fail("Escolha um coordenador: o cabo só fica abaixo do administrador quando não há coordenadores ativos.", "parentId");
    }
    return { ok: true, role, parentId };
  }
  return fail("O cabo eleitoral deve ficar abaixo de um coordenador.", "parentId");
}

/**
 * O ator pode gerenciar (editar, ativar/desativar, redefinir senha, excluir) o membro?
 * ADMIN: qualquer membro da campanha. COORDENADOR: apenas os seus cabos. CABO: ninguém.
 * O chamador garante que o alvo é da mesma campanha (carregado com teamScopeWhere).
 */
export function canManageMember(actor: TeamActor, target: Pick<TeamTarget, "id" | "role" | "parentId">): boolean {
  if (actor.role === "ADMIN") return true;
  if (actor.role === "COORDENADOR") return target.id !== actor.id && target.role === "CABO" && target.parentId === actor.id;
  return false;
}

export type GuardedOperation = "deactivate" | "delete" | "reset_password";

/**
 * Travas comuns: ninguém desativa/exclui/redefine a senha de si mesmo por aqui,
 * e a campanha nunca fica sem administrador ativo.
 * `otherActiveAdmins` = administradores ativos da campanha, exceto o alvo.
 */
export function checkSelfAndLastAdmin(
  operation: GuardedOperation,
  actorId: string,
  target: Pick<TeamTarget, "id" | "role" | "active">,
  otherActiveAdmins: number,
): string | null {
  if (target.id === actorId) {
    if (operation === "deactivate") return "Você não pode desativar o seu próprio acesso.";
    if (operation === "delete") return "Você não pode excluir o seu próprio usuário.";
    return "Para trocar a sua senha, use a página Meu perfil.";
  }
  if (target.role === "ADMIN" && otherActiveAdmins === 0) {
    if (operation === "deactivate" && target.active) return "Não é possível desativar o último administrador ativo da campanha.";
    if (operation === "delete") return "Não é possível excluir o último administrador da campanha.";
  }
  return null;
}

/**
 * Mudança de papel (somente ADMIN): nunca o próprio papel, nunca deixar a campanha sem administrador ativo
 * e só para quem não tem membros vinculados (ex.: coordenador → cabo exige que ele não tenha cabos).
 */
export function validateRoleChange(input: {
  actor: TeamActor;
  target: Pick<TeamTarget, "id" | "role" | "active">;
  newRole: string;
  childrenCount: number;
  otherActiveAdmins: number;
}): string | null {
  const { actor, target, newRole } = input;
  if (newRole === target.role) return null;
  if (actor.role !== "ADMIN") return "Apenas administradores podem alterar o papel de um membro.";
  if (!isCampaignRole(newRole)) return "Papel inválido.";
  if (target.id === actor.id) return "Você não pode alterar o seu próprio papel.";
  if (target.role === "ADMIN" && target.active && input.otherActiveAdmins === 0) {
    return "Não é possível alterar o papel do último administrador ativo da campanha.";
  }
  if (input.childrenCount > 0) {
    const n = input.childrenCount;
    return `Este membro tem ${n} ${n === 1 ? "membro vinculado" : "membros vinculados"}. Mova-os para outro responsável antes de alterar o papel.`;
  }
  return null;
}

export type DeletePlanResult = { ok: true } | { ok: false; error: string; field: "transferToId" | "newParentId" | null };

/**
 * Exclusão de membro: se ele tem eleitores, é obrigatório transferi-los para outro membro ativo do escopo;
 * se tem membros vinculados, é obrigatório escolher o novo responsável deles.
 * `transferTo` deve ter sido carregado dentro do escopo do ator; `newParent`, dentro da campanha.
 */
export function validateDeletePlan(input: {
  target: Pick<TeamTarget, "id" | "role">;
  votersCount: number;
  childrenCount: number;
  transferTo: ParentCandidate | null;
  newParent: ParentCandidate | null;
  /** Há outros coordenadores ativos além do excluído? */
  hasOtherActiveCoordinators: boolean;
}): DeletePlanResult {
  const { target } = input;
  if (input.votersCount > 0) {
    const t = input.transferTo;
    if (!t) return { ok: false, error: "Escolha para quem transferir os eleitores cadastrados por este membro.", field: "transferToId" };
    if (t.id === target.id) return { ok: false, error: "Escolha outro membro para receber os eleitores.", field: "transferToId" };
    if (!t.active) return { ok: false, error: "O membro que vai receber os eleitores está inativo.", field: "transferToId" };
  }
  if (input.childrenCount > 0) {
    const p = input.newParent;
    if (!p) return { ok: false, error: "Escolha o novo responsável pelos membros vinculados.", field: "newParentId" };
    if (p.id === target.id) return { ok: false, error: "Escolha outro responsável.", field: "newParentId" };
    if (!p.active) return { ok: false, error: "O novo responsável está inativo.", field: "newParentId" };
    if (target.role === "ADMIN") {
      if (p.role !== "ADMIN") return { ok: false, error: "Os membros vinculados a um administrador devem passar para outro administrador.", field: "newParentId" };
    } else if (p.role === "ADMIN") {
      if (input.hasOtherActiveCoordinators) {
        return { ok: false, error: "Escolha um coordenador ativo para receber os cabos eleitorais.", field: "newParentId" };
      }
    } else if (p.role !== "COORDENADOR") {
      return { ok: false, error: "Os cabos eleitorais devem passar para um coordenador.", field: "newParentId" };
    }
  }
  return { ok: true };
}

/** Início do dia de hoje no fuso de São Paulo (sem horário de verão desde 2019: UTC−3) */
export function startOfDayInSaoPaulo(now: Date = new Date()): Date {
  const ymd = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Sao_Paulo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
  return new Date(`${ymd}T00:00:00-03:00`);
}

/** Mensagem com os dados de acesso para enviar ao membro (WhatsApp ou copiar) */
export function buildAccessMessage(input: {
  memberName: string;
  campaignName: string;
  role: CampaignRole;
  loginUrl: string;
  email: string;
  password: string;
  registrationUrl?: string | null;
  reset?: boolean;
}): string {
  const first = input.memberName.trim().split(/\s+/)[0] || input.memberName;
  const lines = [
    input.reset
      ? `Olá, ${first}! Sua senha de acesso ao E-Find (campanha ${input.campaignName}) foi redefinida.`
      : `Olá, ${first}! Você foi cadastrado(a) como ${ROLE_LABELS[input.role].toLowerCase()} na equipe da campanha ${input.campaignName} no E-Find.`,
    "",
    `Acesse: ${input.loginUrl}`,
    `E-mail: ${input.email}`,
    `Senha provisória: ${input.password}`,
  ];
  if (input.registrationUrl) {
    lines.push("", `Seu link para cadastrar eleitores: ${input.registrationUrl}`);
  }
  lines.push("", "Por segurança, troque a senha no primeiro acesso (menu Meu perfil).");
  return lines.join("\n");
}
