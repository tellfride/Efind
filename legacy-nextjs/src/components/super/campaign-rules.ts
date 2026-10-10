// Regras puras da campanha compartilhadas entre o formulário (cliente) e a validação no servidor.
import type { Office } from "@/lib/constants";

export const DEFAULT_PRIMARY_COLOR = "#4f46e5";

/**
 * Quantidade de dígitos do número de urna por cargo (Código Eleitoral / TSE):
 * majoritários 2, senador 3, deputado federal 4, deputado estadual/distrital e vereador 5.
 * null = qualquer tamanho entre 2 e 5.
 */
export function expectedBallotNumberLength(office: Office): number | null {
  switch (office) {
    case "PREFEITO":
    case "VICE_PREFEITO":
    case "GOVERNADOR":
    case "PRESIDENTE":
      return 2;
    case "SENADOR":
      return 3;
    case "DEPUTADO_FEDERAL":
      return 4;
    case "DEPUTADO_ESTADUAL":
    case "DEPUTADO_DISTRITAL":
    case "VEREADOR":
      return 5;
    default:
      return null;
  }
}
