// Ordenação e posições dos rankings (puro — usado no cliente e testado em tests/dashboard*.test.ts)
import type { MemberRankingRow } from "@/lib/dashboard-types";

export type MemberSortKey = "inPeriod" | "total" | "goalPct" | "lastAt" | "name";
export type SortDir = "asc" | "desc";

export const MEMBER_SORT_LABELS: Record<MemberSortKey, string> = {
  inPeriod: "Cadastros no período",
  total: "Total de cadastros",
  goalPct: "% da meta",
  lastAt: "Último cadastro",
  name: "Nome",
};

/** Direção natural ao escolher uma coluna (métricas: maior primeiro; nome: A→Z) */
export function defaultSortDir(key: MemberSortKey): SortDir {
  return key === "name" ? "asc" : "desc";
}

function metric(row: MemberRankingRow, key: Exclude<MemberSortKey, "name">): number | null {
  if (key === "lastAt") return row.lastAt ? new Date(row.lastAt).getTime() : null;
  return row[key];
}

/** Ordena sem alterar o array original. Valores ausentes (sem meta, sem cadastro) vão sempre para o fim. */
export function sortMemberRows(rows: MemberRankingRow[], key: MemberSortKey, dir: SortDir): MemberRankingRow[] {
  const sign = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    if (key === "name") return sign * a.name.localeCompare(b.name, "pt-BR");
    const va = metric(a, key);
    const vb = metric(b, key);
    if (va === null && vb === null) return a.name.localeCompare(b.name, "pt-BR");
    if (va === null) return 1;
    if (vb === null) return -1;
    if (va !== vb) return sign * (va - vb);
    // Desempate: total, depois nome
    return b.total - a.total || a.name.localeCompare(b.name, "pt-BR");
  });
}

/**
 * Posições no estilo "competição" (1, 1, 3) para valores já ordenados de forma decrescente.
 * null para valores ausentes.
 */
export function competitionRanks(values: (number | null)[]): (number | null)[] {
  const ranks: (number | null)[] = [];
  let lastValue: number | null = null;
  let lastRank = 0;
  values.forEach((v, i) => {
    if (v === null) {
      ranks.push(null);
      return;
    }
    if (lastValue === null || v !== lastValue) {
      lastRank = i + 1;
      lastValue = v;
    }
    ranks.push(lastRank);
  });
  return ranks;
}

export type RankedMemberRow = MemberRankingRow & {
  /** Posição no ranking (só quando ordenado por uma métrica, do maior para o menor) */
  rank: number | null;
  /** 1, 2 ou 3 — medalha de ouro/prata/bronze (só para quem tem valor > 0) */
  medal: 1 | 2 | 3 | null;
};

export function rankMemberRows(rows: MemberRankingRow[], key: MemberSortKey, dir: SortDir): RankedMemberRow[] {
  const sorted = sortMemberRows(rows, key, dir);
  const ranked = key !== "name" && key !== "lastAt" && dir === "desc";
  const ranks = ranked ? competitionRanks(sorted.map((r) => metric(r, key))) : sorted.map(() => null);
  return sorted.map((row, i) => {
    const rank = ranks[i];
    const value = key === "name" || key === "lastAt" ? null : metric(row, key);
    const medal = rank !== null && rank <= 3 && value !== null && value > 0 ? (rank as 1 | 2 | 3) : null;
    return { ...row, rank, medal };
  });
}
