"""Formatação do WhatsApp (*negrito*, _itálico_, ~tachado~, ```monoespaçado```) convertida em uma árvore de nós.

Lógica pura. O JavaScript do editor (static/js/messaging/whatsapp-format.js) implementa as MESMAS regras para a
pré-visualização ao vivo; mantenha os dois em sincronia. A saída HTML é gerada a partir dos nós com escape
do texto (nunca interpola HTML do usuário).

Nós: {"type": "text", "text": str} | {"type": "break"} | {"type": "bold|italic|strike|mono", "children": [nós]}
"""

from __future__ import annotations

import unicodedata
from typing import Any

from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe

Node = dict[str, Any]

_MARKERS = {"*": "bold", "_": "italic", "~": "strike"}
_TAGS = {"bold": "strong", "italic": "em", "strike": "s", "mono": "code"}


def _at(chars: list[str], index: int) -> str | None:
    return chars[index] if 0 <= index < len(chars) else None


def _is_space(ch: str | None) -> bool:
    return ch is None or ch.isspace()


def _is_boundary(ch: str | None) -> bool:
    """Fronteira válida antes de abrir / depois de fechar um marcador: início/fim, espaço ou pontuação/símbolo."""
    return ch is None or ch.isspace() or unicodedata.category(ch)[0] in ("P", "S")


def _find_close(chars: list[str], marker: str, start: int) -> int:
    for j in range(start + 1, len(chars)):
        ch = chars[j]
        if ch == "\n":  # estilos inline não atravessam linhas
            return -1
        if ch == marker and not _is_space(_at(chars, j - 1)) and _is_boundary(_at(chars, j + 1)):
            return j
    return -1


def _push_text(out: list[Node], text: str) -> None:
    if not text:
        return
    for i, line in enumerate(text.split("\n")):
        if i > 0:
            out.append({"type": "break"})
        if not line:
            continue
        if out and out[-1]["type"] == "text":
            out[-1]["text"] += line
        else:
            out.append({"type": "text", "text": line})


def _parse(chars: list[str]) -> list[Node]:
    out: list[Node] = []
    buf: list[str] = []
    i = 0
    n = len(chars)
    while i < n:
        # ```monoespaçado``` (pode atravessar linhas, sem formatação interna)
        if chars[i : i + 3] == ["`", "`", "`"]:
            end = -1
            for k in range(i + 3, n - 2):
                if chars[k : k + 3] == ["`", "`", "`"]:
                    end = k
                    break
            if end > i + 3:
                _push_text(out, "".join(buf))
                buf = []
                inner: list[Node] = []
                _push_text(inner, "".join(chars[i + 3 : end]))
                out.append({"type": "mono", "children": inner})
                i = end + 3
                continue
        ch = chars[i]
        style = _MARKERS.get(ch)
        if style and _is_boundary(_at(chars, i - 1)) and not _is_space(_at(chars, i + 1)):
            close = _find_close(chars, ch, i)
            if close > i + 1:
                _push_text(out, "".join(buf))
                buf = []
                out.append({"type": style, "children": _parse(chars[i + 1 : close])})
                i = close + 1
                continue
        buf.append(ch)
        i += 1
    _push_text(out, "".join(buf))
    return out


def parse_whatsapp_formatting(text: str | None) -> list[Node]:
    """Converte o texto com marcações do WhatsApp em nós (quebras de linha viram nós "break")."""
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    return _parse(list(normalized))


def nodes_to_plain_text(nodes: list[Node]) -> str:
    """Texto sem as marcações (para resumos)."""
    parts = []
    for node in nodes:
        if node["type"] == "text":
            parts.append(node["text"])
        elif node["type"] == "break":
            parts.append("\n")
        else:
            parts.append(nodes_to_plain_text(node["children"]))
    return "".join(parts)


def nodes_to_html(nodes: list[Node]) -> str:
    parts = []
    for node in nodes:
        kind = node["type"]
        if kind == "text":
            parts.append(escape(node["text"]))
        elif kind == "break":
            parts.append("<br>")
        else:
            tag = _TAGS[kind]
            parts.append(f"<{tag}>{nodes_to_html(node['children'])}</{tag}>")
    return "".join(parts)


def format_whatsapp_html(text: str | None) -> SafeString:
    """Texto do WhatsApp → HTML seguro (<strong>, <em>, <s>, <code>, <br>)."""
    return mark_safe(nodes_to_html(parse_whatsapp_formatting(text)))  # noqa: S308 — tags geradas por nós; texto escapado


def plain_excerpt(text: str | None, limit: int = 140) -> str:
    """Resumo em texto puro (sem marcações) para listas."""
    plain = " ".join(nodes_to_plain_text(parse_whatsapp_formatting(text)).split())
    return plain if len(plain) <= limit else plain[: limit - 1].rstrip() + "…"
