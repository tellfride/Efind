"""Catálogo de widgets dos dashboards e validação do JSON salvo em `Dashboard.widgets`.

Um widget é um dict simples e serializável em JSON:

    {"id": "vg-ranking", "type": "ranking_members", "size": "full",
     "config": {"period": 30, "limit": 10, "filters": {...}, "text": "...", "title": "..."}}

`config` só aceita as opções que o tipo suporta (veja `WidgetDefinition`); o resto é descartado.
Este módulo é puro (sem banco): é usado pelo servidor (salvar/calcular) e serializado para o montador (JS).
"""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ValidationError

from apps.core.permissions import can
from apps.core.voter_filters import sanitize_voter_filters

# ---------------------------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------------------------

WIDGET_SIZES = ("sm", "md", "lg", "full")
WIDGET_SIZE_LABELS = {
    "sm": {"short": "P", "long": "Pequeno (1 coluna)"},
    "md": {"short": "M", "long": "Médio (2 colunas)"},
    "lg": {"short": "G", "long": "Grande (3 colunas)"},
    "full": {"short": "Inteiro", "long": "Largura inteira"},
}

WIDGET_PERIODS = (7, 30, 90, 365)
WIDGET_PERIOD_LABELS = {7: "Últimos 7 dias", 30: "Últimos 30 dias", 90: "Últimos 90 dias", 365: "Últimos 12 meses"}
DEFAULT_PERIOD = 30

MAX_WIDGETS = 30
MAX_NOTE_LENGTH = 2000
MAX_WIDGET_TITLE = 80

WIDGET_GROUPS = (
    ("indicadores", "Indicadores"),
    ("equipe", "Equipe"),
    ("territorio", "Território"),
    ("perfil", "Perfil do eleitor"),
    ("whatsapp", "WhatsApp"),
    ("outros", "Outros"),
)
WIDGET_GROUP_KEYS = tuple(k for k, _ in WIDGET_GROUPS)

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


# ---------------------------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class WidgetDefinition:
    type: str
    label: str
    description: str
    group: str
    icon: str  # nome do ícone Lucide em static/icons/
    default_size: str = "sm"
    period: bool = False  # aceita config.period
    limit: tuple[int, int, int] | None = None  # (mínimo, máximo, padrão) de config.limit
    filters: bool = False  # aceita config.filters (filtros de eleitores)
    text: bool = False  # aceita config.text
    requires: str = ""  # módulo cuja permissão "view" é exigida para ver os dados ("eleitores" | "disparos")

    def options(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "limit": {"min": self.limit[0], "max": self.limit[1], "default": self.limit[2]} if self.limit else None,
            "filters": self.filters,
            "text": self.text,
        }


def _d(type_: str, label: str, description: str, group: str, icon: str, size: str = "sm", **options) -> WidgetDefinition:
    return WidgetDefinition(type_, label, description, group, icon, size, **options)


WIDGET_CATALOG: dict[str, WidgetDefinition] = {
    d.type: d
    for d in (
        # --- Indicadores
        _d("kpi_total", "Total de eleitores", "Quantidade de eleitores cadastrados e o crescimento nos últimos 7 dias.",
           "indicadores", "users-round", filters=True),
        _d("kpi_today", "Cadastros hoje", "Cadastros feitos hoje, comparados com ontem.",
           "indicadores", "calendar", filters=True),
        _d("kpi_period", "Cadastros no período", "Cadastros no período escolhido e a variação em relação ao período anterior.",
           "indicadores", "trending-up", period=True, filters=True),
        _d("kpi_goal", "Meta de cadastros", "Progresso em relação à meta da campanha (ou à soma das metas da sua equipe).",
           "indicadores", "target", filters=True),
        _d("timeline", "Evolução dos cadastros", "Gráfico com os cadastros dia a dia no período.",
           "indicadores", "chart-line", "lg", period=True, filters=True),
        # --- Equipe
        _d("kpi_team", "Equipe ativa", "Membros ativos da equipe e quantos cadastraram eleitores no período.",
           "equipe", "users", period=True, filters=True),
        _d("ranking_members", "Cadastros por cabo eleitoral",
           "Ranking da equipe: total, cadastros no período, meta e último cadastro de cada membro.",
           "equipe", "trophy", "full", period=True, limit=(3, 100, 10), filters=True),
        _d("ranking_coordinators", "Desempenho por coordenador",
           "Cadastros de cada coordenador somados aos dos cabos eleitorais da sua rede.",
           "equipe", "layers", "full", period=True, limit=(3, 50, 10), filters=True),
        _d("goals_progress", "Metas individuais", "Progresso de cada membro em relação à sua meta individual de cadastros.",
           "equipe", "flag", "md", limit=(3, 50, 10), filters=True),
        # --- Território
        _d("by_neighborhood", "Eleitores por bairro", "Bairros com mais eleitores cadastrados.",
           "territorio", "map-pin", "md", limit=(3, 30, 10), filters=True),
        _d("by_city", "Eleitores por cidade", "Cidades com mais eleitores cadastrados.",
           "territorio", "building-2", "md", limit=(3, 30, 10), filters=True),
        # --- Perfil do eleitor
        _d("by_gender", "Gênero", "Distribuição dos eleitores por gênero.",
           "perfil", "venus-and-mars", "md", filters=True),
        _d("by_support", "Nível de apoio", "Apoiadores, simpatizantes, indecisos e opositores.",
           "perfil", "handshake", "md", filters=True),
        _d("by_source", "Origem do cadastro", "Cadastros feitos por link, QR Code, manualmente ou por importação.",
           "perfil", "qr-code", "md", filters=True),
        _d("by_age", "Faixa etária", "Eleitores por faixa de idade (16–24, 25–34, 35–44, 45–59 e 60+).",
           "perfil", "cake", "md", filters=True),
        # --- WhatsApp
        _d("kpi_messageable", "Aptos a WhatsApp", "Eleitores que aceitaram receber mensagens e não pediram descadastro.",
           "whatsapp", "message-circle", filters=True),
        _d("broadcasts", "Disparos de WhatsApp",
           "Mensagens enviadas, entregues, lidas e com falha, além dos últimos disparos.",
           "whatsapp", "send", "full", period=True, requires="disparos"),
        # --- Outros
        _d("recent_voters", "Últimos cadastros", "Os eleitores cadastrados mais recentemente e quem os cadastrou.",
           "outros", "clock", "md", limit=(3, 20, 8), filters=True, requires="eleitores"),
        _d("note", "Recado para a equipe", "Texto livre: avisos, orientações ou metas da semana.",
           "outros", "megaphone", "full", text=True),
    )
}
WIDGET_TYPES = tuple(WIDGET_CATALOG)

# Ícones usados pela interface do módulo (além dos do catálogo) — o servidor os embute na página
UI_ICONS = (
    "arrow-down", "arrow-up", "circle-alert", "clock", "grip-vertical", "inbox", "lock", "medal", "minus",
    "refresh-cw", "sliders-horizontal", "table", "trash-2", "trending-down", "trending-up", "trophy", "x",
    "chart-column", "users",
)  # fmt: skip


def icon_names() -> list[str]:
    """Todos os ícones que o JS dos dashboards pode precisar (sem repetição, ordem estável)."""
    names = [d.icon for d in WIDGET_CATALOG.values()] + list(UI_ICONS)
    return list(dict.fromkeys(names))


def widget_available(definition: WidgetDefinition, perms) -> bool:
    """O usuário pode ver os dados do tipo? (widgets sem `requires` sempre podem)."""
    return not definition.requires or can(perms, definition.requires, "view")


def catalog_for_client(perms=None) -> list[dict]:
    """Catálogo serializável para o montador (JS). `available` indica se o usuário tem a permissão exigida."""
    return [
        {
            "type": d.type,
            "label": d.label,
            "description": d.description,
            "group": d.group,
            "icon": d.icon,
            "default_size": d.default_size,
            "options": d.options(),
            "requires": d.requires,
            "available": widget_available(d, perms) if perms is not None else True,
        }
        for d in WIDGET_CATALOG.values()
    ]


def catalog_by_group(perms=None) -> list[dict]:
    """Catálogo agrupado na ordem de WIDGET_GROUPS (para telas renderizadas no servidor e testes)."""
    items = catalog_for_client(perms)
    return [{"key": key, "label": label, "items": [i for i in items if i["group"] == key]} for key, label in WIDGET_GROUPS]


# ---------------------------------------------------------------------------------------------
# Valores efetivos
# ---------------------------------------------------------------------------------------------


def effective_period(widget: dict) -> int:
    period = (widget.get("config") or {}).get("period")
    return period if period in WIDGET_PERIODS else DEFAULT_PERIOD


def effective_limit(widget: dict) -> int:
    definition = WIDGET_CATALOG.get(widget.get("type"))
    if definition is None or definition.limit is None:
        return 0
    low, high, default = definition.limit
    value = (widget.get("config") or {}).get("limit")
    if not isinstance(value, int) or isinstance(value, bool):
        value = default
    return max(low, min(high, value))


def widget_title(widget: dict) -> str:
    title = ((widget.get("config") or {}).get("title") or "").strip()
    definition = WIDGET_CATALOG.get(widget.get("type"))
    return title or (definition.label if definition else "")


def widget_data_key(widget: dict) -> str:
    """Dois widgets com a mesma chave mostram os mesmos dados (título, tamanho e texto não entram)."""
    definition = WIDGET_CATALOG[widget["type"]]
    parts: dict[str, Any] = {"type": widget["type"]}
    if definition.period:
        parts["period"] = effective_period(widget)
    if definition.limit:
        parts["limit"] = effective_limit(widget)
    if definition.filters:
        filters = sanitize_voter_filters((widget.get("config") or {}).get("filters"))
        if filters:
            parts["filters"] = {k: sorted(v) if isinstance(v, list) else v for k, v in filters.items()}
    return json.dumps(parts, sort_keys=True, ensure_ascii=False)


def new_widget_id() -> str:
    return "w" + secrets.token_hex(5)


def create_widget(type_: str, id_: str | None = None) -> dict:
    """Widget novo com o tamanho e as opções padrão do catálogo."""
    definition = WIDGET_CATALOG[type_]
    config: dict[str, Any] = {}
    if definition.period:
        config["period"] = DEFAULT_PERIOD
    if definition.limit:
        config["limit"] = definition.limit[2]
    if definition.text:
        config["text"] = ""
    return {"id": id_ or new_widget_id(), "type": type_, "size": definition.default_size, "config": config}


# ---------------------------------------------------------------------------------------------
# Validação / sanitização
# ---------------------------------------------------------------------------------------------


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"-?\d{1,6}", value.strip()):
        return int(value.strip())
    return None


def _sanitize_text(value: Any) -> str:
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def _sanitize_config(definition: WidgetDefinition, raw_widget: dict, strict: bool) -> dict:
    src = raw_widget.get("config")
    if src is None:
        src = {}
    if not isinstance(src, dict):
        if strict:
            raise ValidationError("Configuração de widget inválida.")
        src = {}
    config: dict[str, Any] = {}

    if definition.period and src.get("period") not in (None, ""):
        period = _as_int(src["period"])
        if period in WIDGET_PERIODS:
            config["period"] = period
        elif strict:
            raise ValidationError("Período inválido. Use 7, 30, 90 ou 365 dias.")

    if definition.limit and src.get("limit") not in (None, ""):
        limit = _as_int(src["limit"])
        if limit is not None:
            low, high, _ = definition.limit
            config["limit"] = max(low, min(high, limit))
        elif strict:
            raise ValidationError("Limite inválido.")

    if definition.filters and src.get("filters"):
        raw_filters = src["filters"]
        if isinstance(raw_filters, dict):
            cleaned = sanitize_voter_filters(raw_filters)
            if cleaned:
                config["filters"] = cleaned
        elif strict:
            raise ValidationError("Filtros inválidos.")

    if definition.text and src.get("text") is not None:
        text = _sanitize_text(src["text"])
        if len(text) > MAX_NOTE_LENGTH:
            if strict:
                raise ValidationError(f"O texto pode ter no máximo {MAX_NOTE_LENGTH} caracteres.")
            text = text[:MAX_NOTE_LENGTH]
        config["text"] = text

    title = src.get("title", raw_widget.get("title"))  # versões antigas guardavam o título fora de `config`
    if title:
        title = " ".join(str(title).split())
        if len(title) > MAX_WIDGET_TITLE:
            if strict:
                raise ValidationError(f"O título pode ter no máximo {MAX_WIDGET_TITLE} caracteres.")
            title = title[:MAX_WIDGET_TITLE]
        if title:
            config["title"] = title
    return config


def _sanitize_widget(raw: Any, strict: bool) -> dict:
    if not isinstance(raw, dict):
        raise ValidationError("Widget inválido.")
    widget_id = raw.get("id")
    if not isinstance(widget_id, str) or not _ID_RE.match(widget_id):
        raise ValidationError("Identificador de widget inválido.")
    definition = WIDGET_CATALOG.get(raw.get("type"))
    if definition is None:
        raise ValidationError("Tipo de widget desconhecido.")
    size = raw.get("size")
    if size not in WIDGET_SIZES:
        if strict:
            raise ValidationError("Tamanho de widget inválido.")
        size = definition.default_size
    return {"id": widget_id, "type": definition.type, "size": size, "config": _sanitize_config(definition, raw, strict)}


def validate_widgets(raw: Any) -> list[dict]:
    """Valida e normaliza a lista de widgets recebida do cliente (levanta ValidationError em pt-BR).

    Regras: lista com no máximo 30 itens, ids únicos, tipo/tamanho/período conhecidos; `limit` é limitado ao intervalo do
    tipo; opções que o tipo não suporta são descartadas; `filters` passa por `sanitize_voter_filters`.
    """
    if not isinstance(raw, (list, tuple)):
        raise ValidationError("A lista de widgets é inválida.")
    if len(raw) > MAX_WIDGETS:
        raise ValidationError(f"Um dashboard pode ter no máximo {MAX_WIDGETS} widgets.")
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        widget = _sanitize_widget(item, strict=True)
        if widget["id"] in seen:
            raise ValidationError("Há widgets repetidos.")
        seen.add(widget["id"])
        out.append(widget)
    return out


def parse_stored_widgets(value: Any) -> list[dict]:
    """Lê o JSON salvo no banco de forma tolerante: descarta widgets inválidos em vez de falhar."""
    if not isinstance(value, (list, tuple)):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for item in value:
        try:
            widget = _sanitize_widget(item, strict=False)
        except ValidationError:
            continue
        if widget["id"] in seen:
            continue
        seen.add(widget["id"])
        out.append(widget)
        if len(out) >= MAX_WIDGETS:
            break
    return out


def widget_types_in(widgets: Iterable[dict]) -> list[str]:
    return [w["type"] for w in widgets]
