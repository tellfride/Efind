"""Menu lateral. Caminhos literais (não dependem de url names, então módulos podem evoluir sem quebrar o menu).
`icon` = nome do ícone Lucide em static/icons/. `module` = módulo exigido (permissão "view"). `admin_only`: só ADMIN."""

from __future__ import annotations

from .constants import Role
from .permissions import can

PANEL_NAV = [
    {
        "title": "Visão geral",
        "items": [
            {"href": "/painel/", "label": "Início", "icon": "layout-dashboard", "module": "dashboard", "exact": True},
            {"href": "/painel/dashboards/", "label": "Dashboards", "icon": "chart-column", "module": "dashboard"},
        ],
    },
    {
        "title": "Eleitores",
        "items": [
            {"href": "/painel/eleitores/", "label": "Eleitores", "icon": "users-round", "module": "eleitores"},
            {"href": "/painel/mapa/", "label": "Mapa", "icon": "map", "module": "mapa"},
            {"href": "/painel/meu-link/", "label": "Meu link / QR Code", "icon": "qr-code", "module": "meu_link"},
        ],
    },
    {
        "title": "Equipe",
        "items": [
            {"href": "/painel/equipe/", "label": "Equipe", "icon": "users", "module": "equipe"},
            {"href": "/painel/permissoes/", "label": "Permissões", "icon": "key-round", "admin_only": True},
        ],
    },
    {
        "title": "WhatsApp",
        "items": [
            {"href": "/painel/mensagens/modelos/", "label": "Modelos de mensagem", "icon": "message-square-text", "module": "modelos"},
            {"href": "/painel/mensagens/disparos/", "label": "Disparos", "icon": "send", "module": "disparos"},
            {"href": "/painel/whatsapp/", "label": "Conexão da API", "icon": "plug-zap", "module": "whatsapp"},
        ],
    },
    {
        "title": "Campanha",
        "items": [
            {"href": "/painel/configuracoes/", "label": "Configurações", "icon": "settings", "module": "configuracoes"},
            {"href": "/painel/auditoria/", "label": "Auditoria", "icon": "history", "module": "auditoria"},
        ],
    },
]  # fmt: skip

SUPER_NAV = [
    {
        "title": "Plataforma",
        "items": [
            {"href": "/super/", "label": "Visão geral", "icon": "layout-dashboard", "exact": True},
            {"href": "/super/campanhas/", "label": "Candidatos / campanhas", "icon": "shield-check"},
            {"href": "/super/usuarios/", "label": "Super admins", "icon": "users"},
            {"href": "/super/auditoria/", "label": "Auditoria", "icon": "history"},
        ],
    },
    {"title": "Conta", "items": [{"href": "/super/perfil/", "label": "Meu perfil", "icon": "user-round"}]},
]  # fmt: skip


def _is_active(path: str, item: dict) -> bool:
    href = item["href"]
    return path == href if item.get("exact") else path.startswith(href)


def build_nav(user, perms, path: str) -> list[dict]:
    """Seções do menu visíveis para o usuário, com `active` marcado."""
    sections = SUPER_NAV if user.role == Role.SUPER_ADMIN else PANEL_NAV
    out = []
    for section in sections:
        items = []
        for item in section["items"]:
            if item.get("admin_only") and user.role != Role.ADMIN:
                continue
            if item.get("module") and not can(perms, item["module"], "view"):
                continue
            items.append({**item, "active": _is_active(path, item)})
        if items:
            out.append({"title": section["title"], "items": items})
    return out


def first_accessible_path(user, perms) -> str:
    """Primeira página do menu a que o usuário tem acesso (para redirecionar quando a home não é permitida)."""
    for section in build_nav(user, perms, ""):
        return section["items"][0]["href"]
    return "/painel/perfil/"
