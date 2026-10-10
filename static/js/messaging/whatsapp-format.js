/* Formatação do WhatsApp (*negrito*, _itálico_, ~tachado~, ```monoespaçado```) e pré-visualização.
 *
 * Espelha as regras de apps/messaging/whatsapp_format.py (mantenha os dois em sincronia). O texto do usuário NUNCA
 * entra por innerHTML: a árvore de nós vira elementos DOM e o texto vira nós de texto.
 *
 * API (window.EFindWA): parse, renderInto, bubble, showChat, renderTemplate, extractVariables, unknownVariables,
 * hasOptOut, appendOptOut, wrapSelection, insertAt, codePointLength.
 */
(function () {
  "use strict";

  const MARKERS = { "*": "bold", _: "italic", "~": "strike" };
  const TAGS = { bold: "strong", italic: "em", strike: "s", mono: "code" };
  const TAG_CLASS = { mono: "rounded bg-black/5 px-1 font-mono text-[0.92em]" };
  const SPACE_RE = /\s/;
  const BOUNDARY_RE = /[\p{P}\p{S}]/u;

  const at = (chars, i) => (i >= 0 && i < chars.length ? chars[i] : null);
  const isSpace = (ch) => ch === null || SPACE_RE.test(ch);
  // Fronteira válida antes de abrir / depois de fechar um marcador: início/fim, espaço, pontuação ou símbolo
  const isBoundary = (ch) => ch === null || SPACE_RE.test(ch) || BOUNDARY_RE.test(ch);

  function findClose(chars, marker, start) {
    for (let j = start + 1; j < chars.length; j++) {
      const ch = chars[j];
      if (ch === "\n") return -1; // estilos inline não atravessam linhas
      if (ch === marker && !isSpace(at(chars, j - 1)) && isBoundary(at(chars, j + 1))) return j;
    }
    return -1;
  }

  function pushText(out, text) {
    if (!text) return;
    text.split("\n").forEach((line, i) => {
      if (i > 0) out.push({ type: "break" });
      if (!line) return;
      const last = out[out.length - 1];
      if (last && last.type === "text") last.text += line;
      else out.push({ type: "text", text: line });
    });
  }

  function parseChars(chars) {
    const out = [];
    let buf = [];
    let i = 0;
    const n = chars.length;
    while (i < n) {
      if (chars[i] === "`" && chars[i + 1] === "`" && chars[i + 2] === "`") {
        let end = -1;
        for (let k = i + 3; k < n - 2; k++) {
          if (chars[k] === "`" && chars[k + 1] === "`" && chars[k + 2] === "`") {
            end = k;
            break;
          }
        }
        if (end > i + 3) {
          pushText(out, buf.join(""));
          buf = [];
          const inner = [];
          pushText(inner, chars.slice(i + 3, end).join(""));
          out.push({ type: "mono", children: inner });
          i = end + 3;
          continue;
        }
      }
      const ch = chars[i];
      const style = MARKERS[ch];
      if (style && isBoundary(at(chars, i - 1)) && !isSpace(at(chars, i + 1))) {
        const close = findClose(chars, ch, i);
        if (close > i + 1) {
          pushText(out, buf.join(""));
          buf = [];
          out.push({ type: style, children: parseChars(chars.slice(i + 1, close)) });
          i = close + 1;
          continue;
        }
      }
      buf.push(ch);
      i += 1;
    }
    pushText(out, buf.join(""));
    return out;
  }

  /** Texto com marcações → árvore de nós ({type:"text"|"break"|"bold"|"italic"|"strike"|"mono"}) */
  function parse(text) {
    return parseChars(Array.from(String(text || "").replace(/\r\n?/g, "\n")));
  }

  function toDom(nodes, parent) {
    nodes.forEach((node) => {
      if (node.type === "text") parent.appendChild(document.createTextNode(node.text));
      else if (node.type === "break") parent.appendChild(document.createElement("br"));
      else {
        const el = document.createElement(TAGS[node.type]);
        if (TAG_CLASS[node.type]) el.className = TAG_CLASS[node.type];
        toDom(node.children, el);
        parent.appendChild(el);
      }
    });
    return parent;
  }

  /** Substitui o conteúdo de `el` pelo texto formatado (nós DOM, sem innerHTML) */
  function renderInto(el, text) {
    el.replaceChildren();
    toDom(parse(text), el);
    return el;
  }

  function nowLabel() {
    try {
      return new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
    } catch (e) {
      return "";
    }
  }

  /** Balão de mensagem enviada (verde). `media` = rótulo do tipo de mídia ("Imagem", "Documento (PDF)", "Vídeo") */
  function bubble(text, media) {
    const wrap = document.createElement("div");
    wrap.className =
      "ml-auto w-fit max-w-[92%] rounded-lg rounded-tr-none bg-whatsapp-bubble px-2.5 py-1.5 text-[13px] leading-snug text-slate-900 shadow-sm";
    if (media) {
      const box = document.createElement("div");
      box.className =
        "mb-1.5 flex h-24 items-center justify-center rounded-md bg-slate-200/80 px-2 text-center text-xs font-medium text-slate-600";
      box.textContent = media;
      wrap.appendChild(box);
    }
    const body = document.createElement("div");
    body.className = "break-words whitespace-pre-wrap";
    renderInto(body, text);
    wrap.appendChild(body);
    const meta = document.createElement("div");
    meta.className = "mt-0.5 text-right text-[10px] text-slate-500";
    meta.textContent = nowLabel() + " ✓✓";
    wrap.appendChild(meta);
    return wrap;
  }

  /** Mostra uma ou mais mensagens (array de textos ou um texto) dentro do contêiner da maquete do celular */
  function showChat(container, texts, media) {
    if (!container) return;
    container.replaceChildren();
    (Array.isArray(texts) ? texts : [texts]).forEach((t) => container.appendChild(bubble(t, media)));
  }

  // ---------------------------------------------------------------- variáveis {{nome}}
  const VAR_RE = /\{\{\s*([a-zA-Z_]+)\s*\}\}/g;

  /** Substitui {{variavel}} pelo valor do contexto (desconhecida/vazia vira "") — igual a render_template() */
  function renderTemplate(body, ctx) {
    return String(body || "").replace(VAR_RE, (m, key) => {
      const v = (ctx || {})[key.toLowerCase()];
      return v === undefined || v === null ? "" : String(v);
    });
  }

  function extractVariables(body) {
    const out = [];
    for (const m of String(body || "").matchAll(VAR_RE)) {
      const k = m[1].toLowerCase();
      if (!out.includes(k)) out.push(k);
    }
    return out;
  }

  function unknownVariables(body, knownKeys) {
    return extractVariables(body).filter((k) => !knownKeys.includes(k));
  }

  // ---------------------------------------------------------------- descadastro
  function hasOptOut(body, keywords) {
    const normalized = String(body || "")
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .toUpperCase();
    return (keywords || []).some((k) => new RegExp("(^|[^A-Z0-9])" + k + "([^A-Z0-9]|$)").test(normalized));
  }

  function appendOptOut(body, instruction) {
    const trimmed = String(body || "").replace(/\s+$/, "");
    return trimmed ? trimmed + "\n\n" + instruction : instruction;
  }

  // ---------------------------------------------------------------- edição do texto
  /** Envolve a seleção com um marcador (ou insere o par vazio). Espaços nas pontas ficam fora do marcador. */
  function wrapSelection(text, start, end, marker) {
    const s = Math.max(0, Math.min(start, text.length));
    const e = Math.max(s, Math.min(end, text.length));
    let selected = text.slice(s, e);
    const lead = (selected.match(/^\s*/) || [""])[0];
    const trail = (selected.match(/\s*$/) || [""])[0];
    selected = selected.slice(lead.length, selected.length - trail.length);
    const before = text.slice(0, s) + lead;
    const next = before + marker + selected + marker + trail + text.slice(e);
    const selStart = before.length + marker.length;
    return { text: next, selectionStart: selStart, selectionEnd: selStart + selected.length };
  }

  function insertAt(text, start, end, snippet) {
    const s = Math.max(0, Math.min(start, text.length));
    const e = Math.max(s, Math.min(end, text.length));
    return { text: text.slice(0, s) + snippet + text.slice(e), cursor: s + snippet.length };
  }

  /** Tamanho em pontos de código (igual ao len() do Python que valida o limite no servidor) */
  function codePointLength(text) {
    return Array.from(String(text || "")).length;
  }

  window.EFindWA = {
    parse,
    renderInto,
    bubble,
    showChat,
    renderTemplate,
    extractVariables,
    unknownVariables,
    hasOptOut,
    appendOptOut,
    wrapSelection,
    insertAt,
    codePointLength,
  };
})();
