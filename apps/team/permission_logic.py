"""Lógica pura da matriz de permissões (sem banco). Usada pelas views e coberta por testes.

  - Matriz do papel: bool por módulo/ação. Desligar "Ver" limpa a linha (sem "Ver" nada vale); ações não
    suportadas pelo módulo ficam sempre falsas; módulos/ações desconhecidos são descartados.
  - Exceções por usuário: três estados por célula (None = herda do papel, True = permitir, False = negar).

O Alpine (static/js/team/permissions.js) aplica as mesmas regras na tela; o servidor SEMPRE renormaliza.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from apps.core.permissions import (
    ACTION_LABELS,
    ACTIONS,
    MODULE_KEYS,
    MODULES,
    PermissionSet,
    default_permissions_for,
    resolve_permissions,
)

TriState = bool | None
OverrideMatrix = dict[str, dict[str, TriState]]

PERM_PREFIX = "perm__"  # name dos checkboxes da matriz do papel: perm__<módulo>__<ação>
OVERRIDE_PREFIX = "ov__"  # name dos selects de exceção: ov__<módulo>__<ação>

TRI_INHERIT, TRI_ALLOW, TRI_DENY = "inherit", "allow", "deny"


def module_actions(module: str) -> tuple[str, ...]:
    """Ações suportadas por um módulo, na ordem das colunas."""
    return tuple(a for a in ACTIONS if a in MODULES[module]["actions"])


def _empty_module() -> dict[str, bool]:
    return {a: False for a in ACTIONS}


def _empty_override_row() -> dict[str, TriState]:
    return {a: None for a in ACTIONS}


# --------------------------------------------------------------------------------------------
# Matriz do papel
# --------------------------------------------------------------------------------------------


def normalize_matrix(raw: Any) -> PermissionSet:
    """Normaliza uma matriz vinda do cliente: ignora módulos desconhecidos, ações não suportadas ficam falsas,
    só aceita `True` literal e linhas sem "Ver" ficam vazias."""
    source = raw if isinstance(raw, Mapping) else {}
    out: PermissionSet = {}
    for module in MODULE_KEYS:
        row = source.get(module)
        row = row if isinstance(row, Mapping) else {}
        p = _empty_module()
        for action in module_actions(module):
            p[action] = row.get(action) is True
        out[module] = p if p["view"] else _empty_module()
    return out


def default_matrix(role: str) -> PermissionSet:
    return normalize_matrix(default_permissions_for(role))


def matrix_from_rows(role: str, rows: Iterable[Mapping[str, Any]]) -> PermissionSet:
    """Matriz atual do papel: linhas RolePermission sobre o padrão (mesma regra usada no login)."""
    return normalize_matrix(resolve_permissions(role, rows))


def matrix_to_rows(matrix: PermissionSet) -> list[dict[str, Any]]:
    """Linhas completas (todas as colunas booleanas) para gravar em RolePermission."""
    rows = []
    for module in MODULE_KEYS:
        row: dict[str, Any] = {"module": module}
        for action in ACTIONS:
            row[f"can_{action}"] = bool(matrix.get(module, {}).get(action)) and action in module_actions(module)
        rows.append(row)
    return rows


def parse_matrix_post(post: Mapping[str, Any]) -> dict[str, dict[str, bool]]:
    """Lê os checkboxes `perm__<módulo>__<ação>` de um POST (somente os suportados; o resto é ignorado)."""
    raw: dict[str, dict[str, bool]] = {}
    for module in MODULE_KEYS:
        raw[module] = {}
        for action in module_actions(module):
            raw[module][action] = post.get(f"{PERM_PREFIX}{module}__{action}") in ("on", "1", "true", "True")
    return raw


@dataclass(frozen=True)
class PermissionChange:
    module: str
    action: str
    before: TriState
    after: TriState


def diff_matrices(before: PermissionSet, after: PermissionSet) -> list[PermissionChange]:
    """Diferenças célula a célula entre duas matrizes de papel."""
    changes = []
    for module in MODULE_KEYS:
        for action in module_actions(module):
            b = bool(before.get(module, {}).get(action))
            a = bool(after.get(module, {}).get(action))
            if a != b:
                changes.append(PermissionChange(module, action, b, a))
    return changes


def _tri_label(value: TriState) -> str:
    if value is None:
        return "herdar"
    return "sim" if value else "não"


def describe_change(change: PermissionChange) -> str:
    """Texto curto para a auditoria (somente nomes de módulo/ação): "Apoiadores · Exportar: não → sim"."""
    return (
        f"{MODULES[change.module]['label']} · {ACTION_LABELS[change.action]}: "
        f"{_tri_label(change.before)} → {_tri_label(change.after)}"
    )


# --------------------------------------------------------------------------------------------
# Exceções por usuário (três estados)
# --------------------------------------------------------------------------------------------


def empty_overrides() -> OverrideMatrix:
    return {m: _empty_override_row() for m in MODULE_KEYS}


def to_tri_state(value: Any) -> TriState:
    """True/"allow" → True; False/"deny" → False; qualquer outra coisa → None (herda)."""
    if value is True or value == TRI_ALLOW:
        return True
    if value is False or value == TRI_DENY:
        return False
    return None


def tri_to_value(value: TriState) -> str:
    """Valor do <select> de três estados."""
    return TRI_INHERIT if value is None else (TRI_ALLOW if value else TRI_DENY)


def _normalize_override_row(module: str, row: Mapping[str, Any], inherited_view: bool | None) -> dict[str, TriState]:
    out = _empty_override_row()
    actions = module_actions(module)
    for action in actions:
        out[action] = to_tri_state(row.get(action))
    if out["view"] is False:  # negar "Ver" anula as demais (não teriam efeito)
        for action in actions:
            if action != "view":
                out[action] = None
        return out
    # Permitir qualquer ação exige "Ver": se o papel não vê o módulo, a exceção passa a permitir "Ver"
    if inherited_view is False and out["view"] is None and any(out[a] is True for a in actions if a != "view"):
        out["view"] = True
    return out


def normalize_overrides(raw: Any, inherited: PermissionSet | None = None) -> OverrideMatrix:
    """Normaliza exceções vindas do cliente. Com `inherited` (matriz do papel), permitir uma ação num módulo que o
    papel não vê também permite "Ver"."""
    source = raw if isinstance(raw, Mapping) else {}
    out: OverrideMatrix = {}
    for module in MODULE_KEYS:
        row = source.get(module)
        row = row if isinstance(row, Mapping) else {}
        out[module] = _normalize_override_row(module, row, inherited[module]["view"] if inherited else None)
    return out


def overrides_from_rows(rows: Iterable[Mapping[str, Any]]) -> OverrideMatrix:
    """Linhas UserPermission → matriz de três estados."""
    out = empty_overrides()
    for row in rows:
        module = row.get("module")
        if module not in MODULES:
            continue
        values = {a: row.get(f"can_{a}") for a in module_actions(module)}
        out[module] = _normalize_override_row(module, values, None)
    return out


def parse_overrides_post(post: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """Lê os selects `ov__<módulo>__<ação>` de um POST (valores: inherit | allow | deny; ausente = herdar)."""
    raw: dict[str, dict[str, str]] = {}
    for module in MODULE_KEYS:
        raw[module] = {}
        for action in module_actions(module):
            raw[module][action] = post.get(f"{OVERRIDE_PREFIX}{module}__{action}") or TRI_INHERIT
    return raw


def serialize_overrides(overrides: OverrideMatrix) -> tuple[list[dict[str, Any]], list[str]]:
    """Converte a matriz em linhas para gravar (upserts) e módulos sem nenhuma exceção (deletes)."""
    upserts: list[dict[str, Any]] = []
    deletes: list[str] = []
    for module in MODULE_KEYS:
        row = overrides.get(module) or _empty_override_row()
        db: dict[str, Any] = {"module": module}
        for action in ACTIONS:
            db[f"can_{action}"] = to_tri_state(row.get(action)) if action in module_actions(module) else None
        if any(db[f"can_{a}"] is not None for a in ACTIONS):
            upserts.append(db)
        else:
            deletes.append(module)
    return upserts, deletes


def count_overrides(overrides: OverrideMatrix) -> int:
    """Quantidade de células com exceção (≠ herdar)."""
    return sum(
        1
        for module in MODULE_KEYS
        for action in module_actions(module)
        if (overrides.get(module) or {}).get(action) is not None
    )


def diff_overrides(before: OverrideMatrix, after: OverrideMatrix) -> list[PermissionChange]:
    changes = []
    for module in MODULE_KEYS:
        for action in module_actions(module):
            b = to_tri_state((before.get(module) or {}).get(action))
            a = to_tri_state((after.get(module) or {}).get(action))
            if a != b:
                changes.append(PermissionChange(module, action, b, a))
    return changes


def effective_permissions(role: str, inherited: PermissionSet, overrides: OverrideMatrix) -> PermissionSet:
    """Permissões efetivas do usuário = matriz do papel + exceções (mesma regra de `resolve_permissions`)."""
    upserts, _ = serialize_overrides(overrides)
    return resolve_permissions(role, matrix_to_rows(inherited), upserts)
