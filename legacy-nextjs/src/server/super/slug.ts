// Slug único de campanha. Puro (sem banco) para ser testável.
import { slugify } from "@/lib/utils";

export const SLUG_MAX_LENGTH = 60;
/** Espaço reservado para o sufixo numérico ("-99999") sem ultrapassar o limite */
const SUFFIX_RESERVE = 6;

/** Base do slug a partir do nome de urna; "campanha" quando não sobra nenhum caractere válido */
export function campaignSlugBase(ballotName: string): string {
  const base = slugify(ballotName)
    .slice(0, SLUG_MAX_LENGTH - SUFFIX_RESERVE)
    .replace(/-+$/g, "");
  return base || "campanha";
}

/** Primeiro slug livre na sequência: base, base-2, base-3... */
export function uniqueSlug(base: string, existing: Iterable<string>): string {
  const taken = new Set(existing);
  if (!taken.has(base)) return base;
  for (let n = 2; ; n++) {
    const candidate = `${base}-${n}`;
    if (!taken.has(candidate)) return candidate;
  }
}
