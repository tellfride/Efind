// Formatação do WhatsApp (*negrito*, _itálico_, ~tachado~, ```monoespaçado```) convertida em uma
// árvore de nós — a pré-visualização monta elementos React a partir dela (sem HTML cru).
// Puro: usado no cliente (editor/pré-visualização) e nos testes.
import { OPT_OUT_KEYWORDS } from "@/lib/constants";

export type FormatStyle = "bold" | "italic" | "strike" | "mono";

export type FormatNode =
  | { type: "text"; text: string }
  | { type: "break" }
  | { type: FormatStyle; children: FormatNode[] };

const MARKERS: Record<string, Exclude<FormatStyle, "mono">> = { "*": "bold", _: "italic", "~": "strike" };

const isSpace = (ch: string | undefined) => ch === undefined || /\s/.test(ch);
/** Fronteira válida antes de abrir / depois de fechar um marcador: início/fim, espaço ou pontuação */
const isBoundary = (ch: string | undefined) => ch === undefined || /[\s\p{P}\p{S}]/u.test(ch);

function findClose(s: string, marker: string, from: number): number {
  for (let j = from + 1; j < s.length; j++) {
    const ch = s[j];
    if (ch === "\n") return -1; // estilos inline não atravessam linhas
    if (ch === marker && !isSpace(s[j - 1]) && isBoundary(s[j + 1])) return j;
  }
  return -1;
}

function pushText(out: FormatNode[], text: string) {
  if (!text) return;
  const lines = text.split("\n");
  lines.forEach((line, i) => {
    if (i > 0) out.push({ type: "break" });
    if (!line) return;
    const last = out[out.length - 1];
    if (last && last.type === "text") last.text += line;
    else out.push({ type: "text", text: line });
  });
}

function parse(s: string): FormatNode[] {
  const out: FormatNode[] = [];
  let buf = "";
  let i = 0;
  while (i < s.length) {
    // ```monoespaçado``` (pode atravessar linhas, sem formatação interna)
    if (s.startsWith("```", i)) {
      const end = s.indexOf("```", i + 3);
      if (end > i + 3) {
        pushText(out, buf);
        buf = "";
        const inner: FormatNode[] = [];
        pushText(inner, s.slice(i + 3, end));
        out.push({ type: "mono", children: inner });
        i = end + 3;
        continue;
      }
    }
    const ch = s[i];
    const style = MARKERS[ch];
    if (style && isBoundary(s[i - 1]) && !isSpace(s[i + 1])) {
      const close = findClose(s, ch, i);
      if (close > i + 1) {
        pushText(out, buf);
        buf = "";
        out.push({ type: style, children: parse(s.slice(i + 1, close)) });
        i = close + 1;
        continue;
      }
    }
    buf += ch;
    i++;
  }
  pushText(out, buf);
  return out;
}

/** Converte o texto com marcações do WhatsApp em nós (quebras de linha viram nós "break") */
export function parseWhatsAppFormatting(text: string): FormatNode[] {
  return parse(text.replace(/\r\n?/g, "\n"));
}

/** Texto sem as marcações (para resumos) */
export function nodesToPlainText(nodes: FormatNode[]): string {
  return nodes
    .map((n) => (n.type === "text" ? n.text : n.type === "break" ? "\n" : nodesToPlainText(n.children)))
    .join("");
}

export const OPT_OUT_INSTRUCTION = "Responda SAIR para não receber mais mensagens.";

/** O texto explica como deixar de receber mensagens (ex.: "responda SAIR")? */
export function hasOptOutInstruction(body: string): boolean {
  const normalized = body.normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase();
  return OPT_OUT_KEYWORDS.some((k) => new RegExp(`(^|[^A-Z0-9])${k}([^A-Z0-9]|$)`).test(normalized));
}

export function appendOptOutInstruction(body: string): string {
  const trimmed = body.replace(/\s+$/, "");
  return trimmed ? `${trimmed}\n\n${OPT_OUT_INSTRUCTION}` : OPT_OUT_INSTRUCTION;
}

/** Envolve a seleção com um marcador (ou insere o par vazio). Retorna o novo texto e a nova seleção. */
export function wrapSelection(
  text: string,
  start: number,
  end: number,
  marker: string,
): { text: string; selectionStart: number; selectionEnd: number } {
  const s = Math.max(0, Math.min(start, text.length));
  const e = Math.max(s, Math.min(end, text.length));
  let selected = text.slice(s, e);
  // Espaços nas pontas ficam fora do marcador (senão o WhatsApp não formata)
  const lead = selected.match(/^\s*/)?.[0] ?? "";
  const trail = selected.match(/\s*$/)?.[0] ?? "";
  selected = selected.slice(lead.length, selected.length - trail.length);
  const before = text.slice(0, s) + lead;
  const next = `${before}${marker}${selected}${marker}${trail}${text.slice(e)}`;
  const selStart = before.length + marker.length;
  return { text: next, selectionStart: selStart, selectionEnd: selStart + selected.length };
}

/** Insere um trecho na posição do cursor (substituindo a seleção) */
export function insertAt(
  text: string,
  start: number,
  end: number,
  snippet: string,
): { text: string; cursor: number } {
  const s = Math.max(0, Math.min(start, text.length));
  const e = Math.max(s, Math.min(end, text.length));
  return { text: text.slice(0, s) + snippet + text.slice(e), cursor: s + snippet.length };
}
