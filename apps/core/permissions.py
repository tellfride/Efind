"""Matriz de permissões por módulo (lógica pura, sem acesso a banco).

Um `PermissionSet` é um dict {módulo: {ação: bool}} — funciona direto nos templates:
    {% if perms.eleitores.create %}...{% endif %}
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .constants import Role

ACTIONS = ("view", "create", "edit", "delete", "export")
ACTION_LABELS = {"view": "Ver", "create": "Criar", "edit": "Editar", "delete": "Excluir", "export": "Exportar"}

# módulo → (rótulo, descrição, ações suportadas)
MODULES: dict[str, dict[str, Any]] = {
    "dashboard": {
        "label": "Dashboards",
        "description": "Painéis com indicadores. Criar/editar = montar dashboards próprios.",
        "actions": ("view", "create", "edit", "delete"),
    },
    "eleitores": {
        "label": "Eleitores",
        "description": "Cadastro e lista de eleitores (cada usuário vê apenas sua rede).",
        "actions": ("view", "create", "edit", "delete", "export"),
    },
    "mapa": {
        "label": "Mapa",
        "description": "Mapa por bairro/CEP dos eleitores da rede do usuário.",
        "actions": ("view",),
    },
    "meu_link": {
        "label": "Meu link / QR Code",
        "description": "Link e QR Code pessoal para cadastro de eleitores.",
        "actions": ("view",),
    },
    "equipe": {
        "label": "Equipe",
        "description": "Coordenadores e cabos eleitorais. Coordenador gerencia apenas seus cabos.",
        "actions": ("view", "create", "edit", "delete"),
    },
    "modelos": {
        "label": "Modelos de mensagem",
        "description": "Textos com variáveis usados nos disparos.",
        "actions": ("view", "create", "edit", "delete"),
    },
    "disparos": {
        "label": "Disparos de WhatsApp",
        "description": "Envio em massa para eleitores que consentiram. Editar = pausar/retomar/cancelar.",
        "actions": ("view", "create", "edit", "delete"),
    },
    "whatsapp": {
        "label": "API do WhatsApp",
        "description": "Conexões e credenciais dos provedores de WhatsApp.",
        "actions": ("view", "edit"),
    },
    "configuracoes": {
        "label": "Configurações da campanha",
        "description": "Identidade visual, formulário público e textos de consentimento.",
        "actions": ("view", "edit"),
    },
    "auditoria": {
        "label": "Auditoria",
        "description": "Registro de acessos, alterações e exportações (LGPD).",
        "actions": ("view",),
    },
}
MODULE_KEYS = tuple(MODULES)

PermissionSet = dict[str, dict[str, bool]]

# Permissões padrão dos papéis configuráveis (aplicadas ao criar a campanha e quando não há linha no banco)
DEFAULT_ROLE_PERMISSIONS: dict[str, dict[str, tuple[str, ...]]] = {
    Role.COORDENADOR: {
        "dashboard": ("view", "create", "edit", "delete"),
        "eleitores": ("view", "create", "edit", "export"),
        "mapa": ("view",),
        "meu_link": ("view",),
        "equipe": ("view", "create", "edit"),
        "modelos": ("view",),
        "disparos": ("view",),
    },
    Role.CABO: {
        "dashboard": ("view",),
        "eleitores": ("view", "create", "edit"),
        "mapa": ("view",),
        "meu_link": ("view",),
    },
}


def module_supports(module: str, action: str) -> bool:
    return module in MODULES and action in MODULES[module]["actions"]


def _empty_module() -> dict[str, bool]:
    return {a: False for a in ACTIONS}


def _from_actions(module: str, actions: Iterable[str]) -> dict[str, bool]:
    p = _empty_module()
    for a in actions:
        if module_supports(module, a):
            p[a] = True
    return p


def default_permissions_for(role: str) -> PermissionSet:
    defaults = DEFAULT_ROLE_PERMISSIONS.get(role, {})
    return {m: _from_actions(m, defaults.get(m, ())) for m in MODULE_KEYS}


def full_permissions() -> PermissionSet:
    return {m: _from_actions(m, MODULES[m]["actions"]) for m in MODULE_KEYS}


def no_permissions() -> PermissionSet:
    return {m: _empty_module() for m in MODULE_KEYS}


def resolve_permissions(
    role: str,
    role_rows: Iterable[Mapping[str, Any]] = (),
    user_rows: Iterable[Mapping[str, Any]] = (),
) -> PermissionSet:
    """Permissões efetivas.

    - ADMIN: tudo. SUPER_ADMIN: nada dentro de campanhas (usa /super).
    - COORDENADOR/CABO: padrão do papel → linhas RolePermission da campanha → exceções UserPermission
      (valor None = herda). Ações não suportadas pelo módulo ficam sempre False; sem "view",
      nenhuma outra ação vale.

    Cada linha é um mapeamento com as chaves: module, can_view, can_create, can_edit, can_delete, can_export.
    """
    if role == Role.ADMIN:
        return full_permissions()
    if role == Role.SUPER_ADMIN:
        return no_permissions()

    perms = default_permissions_for(role)

    def apply(rows: Iterable[Mapping[str, Any]]) -> None:
        for row in rows:
            module = row.get("module")
            if module not in MODULES:
                continue
            for action in MODULES[module]["actions"]:
                value = row.get(f"can_{action}")
                if value is not None:
                    perms[module][action] = bool(value)

    apply(role_rows)
    apply(user_rows)

    for module in MODULE_KEYS:
        if not perms[module]["view"]:
            perms[module] = _empty_module()
    return perms


def can(perms: PermissionSet | None, module: str, action: str = "view") -> bool:
    return bool(perms and perms.get(module, {}).get(action))
