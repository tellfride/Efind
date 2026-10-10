// Lógica pura da tela de equipe: árvore hierárquica, filtros, ordenação, metas e resumo.
import type { CampaignRole } from "@/lib/constants";
import { normalizeText } from "@/lib/utils";
import type { TeamMemberDTO } from "./types";

export const ROLE_ORDER: Record<CampaignRole, number> = { ADMIN: 0, COORDENADOR: 1, CABO: 2 };

/** Percentual da meta (null quando não há meta definida) */
export function goalPercent(total: number, goal: number | null | undefined): number | null {
  if (!goal || goal <= 0) return null;
  return (total / goal) * 100;
}

export type GoalTone = "green" | "brand" | "yellow" | "red";

/** Cor da barra de progresso da meta */
export function goalTone(percent: number | null): GoalTone {
  if (percent === null) return "brand";
  if (percent >= 100) return "green";
  if (percent >= 50) return "brand";
  if (percent >= 25) return "yellow";
  return "red";
}

const collator = new Intl.Collator("pt-BR", { sensitivity: "base" });

/** Ordem padrão: papel (admin → coordenador → cabo), ativos antes, nome */
export function compareMembers(a: TeamMemberDTO, b: TeamMemberDTO): number {
  return ROLE_ORDER[a.role] - ROLE_ORDER[b.role] || Number(b.active) - Number(a.active) || collator.compare(a.name, b.name);
}

export interface TeamTreeNode {
  member: TeamMemberDTO;
  children: TeamTreeNode[];
  /** Eleitores do membro + de toda a sua rede abaixo */
  networkTotal: number;
  /** Quantidade de membros na subárvore (incluindo ele) */
  size: number;
  /** Membro sem superior visível que deveria ter um (ex.: cabo sem coordenador) */
  detached: boolean;
}

/**
 * Monta a árvore admin → coordenadores → cabos com os membros visíveis.
 * Quem não tem o superior entre os visíveis vira raiz (ex.: o próprio coordenador na visão dele).
 * Protegido contra ciclos em dados inconsistentes.
 */
export function buildTeamTree(members: TeamMemberDTO[]): TeamTreeNode[] {
  const byId = new Map(members.map((m) => [m.id, m]));
  const childrenOf = new Map<string, TeamMemberDTO[]>();
  const roots: TeamMemberDTO[] = [];
  for (const m of members) {
    if (m.parentId && m.parentId !== m.id && byId.has(m.parentId)) {
      const list = childrenOf.get(m.parentId) ?? [];
      list.push(m);
      childrenOf.set(m.parentId, list);
    } else {
      roots.push(m);
    }
  }

  const visited = new Set<string>();
  const build = (m: TeamMemberDTO): TeamTreeNode => {
    visited.add(m.id);
    const kids = (childrenOf.get(m.id) ?? [])
      .filter((k) => !visited.has(k.id))
      .sort(compareMembers)
      .map(build);
    return {
      member: m,
      children: kids,
      networkTotal: m.votersTotal + kids.reduce((s, k) => s + k.networkTotal, 0),
      size: 1 + kids.reduce((s, k) => s + k.size, 0),
      detached: m.role !== "ADMIN" && !m.parentId,
    };
  };

  const tree = [...roots].sort(compareMembers).map(build);
  // Membros presos em ciclo (nunca alcançados a partir de uma raiz) entram como raízes
  for (const m of [...members].sort(compareMembers)) if (!visited.has(m.id)) tree.push(build(m));
  return tree;
}

/** ids de todos os nós que têm filhos (para "expandir tudo") */
export function collectParentIds(nodes: TeamTreeNode[]): string[] {
  const out: string[] = [];
  const walk = (list: TeamTreeNode[]) => {
    for (const n of list) {
      if (n.children.length) {
        out.push(n.member.id);
        walk(n.children);
      }
    }
  };
  walk(nodes);
  return out;
}

export type StatusFilter = "all" | "active" | "inactive";

export interface TeamListFilters {
  q: string;
  role: CampaignRole | "";
  coordinatorId: string;
  status: StatusFilter;
}

export const EMPTY_TEAM_FILTERS: TeamListFilters = { q: "", role: "", coordinatorId: "", status: "all" };

export function filterMembers(members: TeamMemberDTO[], filters: TeamListFilters): TeamMemberDTO[] {
  const q = normalizeText(filters.q);
  const digits = filters.q.replace(/\D/g, "");
  return members.filter((m) => {
    if (filters.role && m.role !== filters.role) return false;
    if (filters.status === "active" && !m.active) return false;
    if (filters.status === "inactive" && m.active) return false;
    if (filters.coordinatorId && m.id !== filters.coordinatorId && m.parentId !== filters.coordinatorId) return false;
    if (q) {
      const text = normalizeText(`${m.name} ${m.email} ${m.region ?? ""}`);
      const phoneMatch = digits.length >= 4 && (m.phone ?? "").replace(/\D/g, "").includes(digits);
      if (!text.includes(q) && !phoneMatch) return false;
    }
    return true;
  });
}

export type TeamSortKey = "voters" | "voters7d" | "goal" | "name";
export interface TeamSort {
  key: TeamSortKey;
  dir: "asc" | "desc";
}

export const DEFAULT_TEAM_SORT: TeamSort = { key: "voters", dir: "desc" };

export function sortMembers(members: TeamMemberDTO[], sort: TeamSort): TeamMemberDTO[] {
  const sign = sort.dir === "asc" ? 1 : -1;
  const value = (m: TeamMemberDTO): number => {
    if (sort.key === "voters") return m.votersTotal;
    if (sort.key === "voters7d") return m.voters7d;
    if (sort.key === "goal") return goalPercent(m.votersTotal, m.goal) ?? -1;
    return 0;
  };
  return [...members].sort((a, b) => {
    if (sort.key === "name") return sign * collator.compare(a.name, b.name);
    return sign * (value(a) - value(b)) || collator.compare(a.name, b.name);
  });
}

export interface TeamSummary {
  total: number;
  byRole: Record<CampaignRole, number>;
  active: number;
  inactive: number;
  voters: number;
  voters7d: number;
  /** Coordenadores e cabos ativos sem nenhum cadastro nos últimos 7 dias */
  idle7d: number;
}

export function summarizeTeam(members: TeamMemberDTO[]): TeamSummary {
  const s: TeamSummary = { total: 0, byRole: { ADMIN: 0, COORDENADOR: 0, CABO: 0 }, active: 0, inactive: 0, voters: 0, voters7d: 0, idle7d: 0 };
  for (const m of members) {
    s.total++;
    s.byRole[m.role]++;
    if (m.active) s.active++;
    else s.inactive++;
    s.voters += m.votersTotal;
    s.voters7d += m.voters7d;
    if (m.active && m.role !== "ADMIN" && m.voters7d === 0) s.idle7d++;
  }
  return s;
}
