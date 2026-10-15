"""Matriz de permissões: /painel/permissoes/ (somente ADMIN).

  - abas por papel (Coordenador / Cabo eleitoral): matriz módulo × ação gravada em `RolePermission`;
  - "Restaurar padrão" volta ao `DEFAULT_ROLE_PERMISSIONS`;
  - exceções por usuário (`UserPermission`) em três estados: herdar / permitir / negar.

O servidor SEMPRE renormaliza o que vem do cliente (`permission_logic`), valida que o usuário-alvo é da campanha do
admin e tem papel configurável, e audita só nomes de módulo/ação (nunca dados pessoais). O efeito é imediato: as
permissões são recalculadas a cada requisição (`request.perms`).
"""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.models import RolePermission, User, UserPermission
from apps.auditlog.service import audit
from apps.core.constants import CONFIGURABLE_ROLES, Role, label_of
from apps.core.decorators import admin_required
from apps.core.permissions import ACTION_LABELS, ACTIONS, MODULE_KEYS, MODULES

from . import queries
from .permission_logic import (
    OVERRIDE_PREFIX,
    PERM_PREFIX,
    PermissionChange,
    count_overrides,
    default_matrix,
    diff_matrices,
    diff_overrides,
    matrix_from_rows,
    matrix_to_rows,
    module_actions,
    normalize_matrix,
    normalize_overrides,
    overrides_from_rows,
    parse_matrix_post,
    parse_overrides_post,
    serialize_overrides,
    tri_to_value,
)

ROLE_TABS = (
    {
        "slug": "coordenador",
        "role": Role.COORDENADOR,
        "label": "Coordenador",
        "description": "Coordenadores veem a própria rede: eles mesmos e os cabos que estão abaixo deles.",
    },
    {
        "slug": "cabo",
        "role": Role.CABO,
        "label": "Cabo eleitoral",
        "description": (
            "Cabos eleitorais veem apenas os apoiadores que eles mesmos cadastraram. "
            "Mesmo com “Criar” em Equipe, cabos não cadastram membros."
        ),
    },
)
TAB_BY_SLUG = {t["slug"]: t for t in ROLE_TABS}
DEFAULT_TAB = ROLE_TABS[0]["slug"]
MAX_CHANGES_IN_AUDIT = 60


# --------------------------------------------------------------------------------------------
# Leitura
# --------------------------------------------------------------------------------------------


def _role_rows(campaign_id, role) -> list[dict[str, Any]]:
    return [r.as_row() for r in RolePermission.objects.filter(campaign_id=campaign_id, role=role)]


def _current_matrix(campaign_id, role):
    return matrix_from_rows(role, _role_rows(campaign_id, role))


def _tab_or_404(slug: str) -> dict[str, Any]:
    tab = TAB_BY_SLUG.get(slug)
    if tab is None:
        raise Http404("Papel não encontrado.")
    return tab


def _count_enabled(matrix) -> int:
    return sum(1 for m in MODULE_KEYS for a in module_actions(m) if matrix[m][a])


TOTAL_CELLS = sum(len(module_actions(m)) for m in MODULE_KEYS)


def _module_rows(matrix, default) -> list[dict[str, Any]]:
    rows = []
    for key in MODULE_KEYS:
        supported = module_actions(key)
        rows.append(
            {
                "key": key,
                "label": MODULES[key]["label"],
                "description": MODULES[key]["description"],
                "cells": [
                    {
                        "action": a,
                        "label": ACTION_LABELS[a],
                        "supported": a in supported,
                        "checked": bool(matrix[key][a]),
                        "default": bool(default[key][a]),
                        "name": f"{PERM_PREFIX}{key}__{a}",
                    }
                    for a in ACTIONS
                ],
            }
        )
    return rows


def _tab_context(campaign_id, tab) -> dict[str, Any]:
    matrix = _current_matrix(campaign_id, tab["role"])
    default = default_matrix(tab["role"])
    return {
        **tab,
        "matrix": matrix,
        "rows": _module_rows(matrix, default),
        "is_default": matrix == default,
        "enabled": _count_enabled(matrix),
        "total": TOTAL_CELLS,
        "save_url": reverse("team:permissions_role_save", args=[tab["slug"]]),
        "reset_url": reverse("team:permissions_role_reset", args=[tab["slug"]]),
    }


def _override_rows(matrix_inherited, overrides) -> list[dict[str, Any]]:
    rows = []
    for key in MODULE_KEYS:
        supported = module_actions(key)
        rows.append(
            {
                "key": key,
                "label": MODULES[key]["label"],
                "description": MODULES[key]["description"],
                "cells": [
                    {
                        "action": a,
                        "label": ACTION_LABELS[a],
                        "supported": a in supported,
                        "value": tri_to_value(overrides[key][a]) if a in supported else "inherit",
                        "inherited": bool(matrix_inherited[key][a]),
                        "name": f"{OVERRIDE_PREFIX}{key}__{a}",
                    }
                    for a in ACTIONS
                ],
            }
        )
    return rows


def _users_with_overrides(campaign_id) -> list[dict[str, Any]]:
    """Usuários da campanha que têm exceções, com a quantidade de células alteradas (1 consulta)."""
    rows_by_user: dict[Any, list[dict[str, Any]]] = {}
    users: dict[Any, User] = {}
    qs = UserPermission.objects.filter(user__campaign_id=campaign_id, user__role__in=CONFIGURABLE_ROLES).select_related(
        "user"
    )
    for row in qs:
        rows_by_user.setdefault(row.user_id, []).append(row.as_row())
        users[row.user_id] = row.user
    out = []
    for user_id, rows in rows_by_user.items():
        count = count_overrides(overrides_from_rows(rows))
        if count:
            user = users[user_id]
            out.append({"user": user, "count": count})
    out.sort(key=lambda item: item["user"].name.lower())
    return out


# --------------------------------------------------------------------------------------------
# Página
# --------------------------------------------------------------------------------------------


@admin_required
def permissions(request):
    campaign_id = request.user.campaign_id
    active_tab = request.GET.get("aba", "")
    if active_tab not in TAB_BY_SLUG:
        active_tab = DEFAULT_TAB

    tabs = [_tab_context(campaign_id, tab) for tab in ROLE_TABS]
    config: dict[str, Any] = {
        "supported": {m: list(module_actions(m)) for m in MODULE_KEYS},
        "roles": {t["slug"]: t["matrix"] for t in tabs},
    }

    configurable = list(User.objects.filter(campaign_id=campaign_id, role__in=CONFIGURABLE_ROLES).order_by("role", "name"))
    selected = None
    selected_missing = False
    override_rows: list[dict[str, Any]] = []
    effective_count = 0
    raw_user_id = request.GET.get("usuario", "")
    if raw_user_id:
        selected = queries.get_campaign_user(campaign_id, raw_user_id, roles=CONFIGURABLE_ROLES)
        selected_missing = selected is None
    override_config = None
    if selected is not None:
        inherited = _current_matrix(campaign_id, selected.role)
        overrides = overrides_from_rows([r.as_row() for r in UserPermission.objects.filter(user=selected)])
        override_rows = _override_rows(inherited, overrides)
        effective_count = count_overrides(overrides)
        override_config = {
            "supported": config["supported"],
            "inherited": inherited,
            "values": {m: {a: tri_to_value(overrides[m][a]) for a in module_actions(m)} for m in MODULE_KEYS},
        }

    context = {
        "tabs": tabs,
        "active_tab": active_tab,
        "perm_config": config,
        "configurable_users": configurable,
        "selected_user": selected,
        "selected_missing": selected_missing,
        "selected_role_label": label_of(Role, selected.role) if selected else "",
        "override_rows": override_rows,
        "override_config": override_config,
        "override_count": effective_count,
        "users_with_overrides": _users_with_overrides(campaign_id),
        "user_save_url": reverse("team:permissions_user_save", args=[selected.pk]) if selected else "",
    }
    return render(request, "team/permissions.html", context)


# --------------------------------------------------------------------------------------------
# Gravação
# --------------------------------------------------------------------------------------------


def _change_payload(changes: list[PermissionChange]) -> list[dict[str, Any]]:
    """Resumo da diferença para a auditoria: somente nomes de módulo/ação e os valores antes/depois."""
    return [
        {"module": c.module, "action": c.action, "from": c.before, "to": c.after}
        for c in changes[:MAX_CHANGES_IN_AUDIT]
    ]


def _write_role_matrix(campaign_id, role, matrix) -> None:
    with transaction.atomic():
        for row in matrix_to_rows(matrix):
            defaults = {k: v for k, v in row.items() if k != "module"}
            RolePermission.objects.update_or_create(
                campaign_id=campaign_id, role=role, module=row["module"], defaults=defaults
            )


def _permissions_redirect(tab_slug: str):
    return redirect(f"{reverse('team:permissions')}?aba={tab_slug}")


@admin_required
@require_POST
def permissions_role_save(request, role_slug):
    tab = _tab_or_404(role_slug)
    campaign_id = request.user.campaign_id
    before = _current_matrix(campaign_id, tab["role"])
    after = normalize_matrix(parse_matrix_post(request.POST))
    _write_role_matrix(campaign_id, tab["role"], after)
    changes = diff_matrices(before, after)
    audit(
        "permissions.update",
        request=request,
        entity="RolePermission",
        details={"scope": "role", "role": tab["role"], "count": len(changes), "changes": _change_payload(changes)},
    )
    if changes:
        n = len(changes)
        messages.success(
            request, f"Permissões de {tab['label'].lower()} salvas ({n} alteraç{'ões' if n != 1 else 'ão'}). Já valem para todos."
        )
    else:
        messages.info(request, "Nenhuma alteração nas permissões.")
    return _permissions_redirect(tab["slug"])


@admin_required
@require_POST
def permissions_role_reset(request, role_slug):
    tab = _tab_or_404(role_slug)
    campaign_id = request.user.campaign_id
    before = _current_matrix(campaign_id, tab["role"])
    after = default_matrix(tab["role"])
    _write_role_matrix(campaign_id, tab["role"], after)
    changes = diff_matrices(before, after)
    audit(
        "permissions.update",
        request=request,
        entity="RolePermission",
        details={
            "scope": "role",
            "role": tab["role"],
            "reset": True,
            "count": len(changes),
            "changes": _change_payload(changes),
        },
    )
    messages.success(request, f"Permissões de {tab['label'].lower()} restauradas para o padrão do E-Find.")
    return _permissions_redirect(tab["slug"])


@admin_required
@require_POST
def permissions_user_save(request, user_id):
    campaign_id = request.user.campaign_id
    target = queries.get_campaign_user(campaign_id, user_id, roles=CONFIGURABLE_ROLES)
    if target is None:
        raise Http404("Usuário não encontrado.")

    inherited = _current_matrix(campaign_id, target.role)
    before = overrides_from_rows([r.as_row() for r in UserPermission.objects.filter(user=target)])
    if request.POST.get("clear"):
        after = normalize_overrides({})
    else:
        after = normalize_overrides(parse_overrides_post(request.POST), inherited)
    upserts, deletes = serialize_overrides(after)
    with transaction.atomic():
        for row in upserts:
            defaults = {k: v for k, v in row.items() if k != "module"}
            UserPermission.objects.update_or_create(user=target, module=row["module"], defaults=defaults)
        # módulos sem nenhuma exceção (ou desconhecidos) não ficam no banco
        UserPermission.objects.filter(user=target).exclude(module__in=[u["module"] for u in upserts]).delete()
    changes = diff_overrides(before, after)
    audit(
        "permissions.update",
        request=request,
        entity="User",
        entity_id=target.pk,
        details={
            "scope": "user",
            "user_id": str(target.pk),
            "cleared": bool(request.POST.get("clear")),
            "count": len(changes),
            "changes": _change_payload(changes),
        },
    )
    if request.POST.get("clear"):
        messages.success(request, "Exceções removidas: o usuário volta a seguir as permissões do papel.")
    elif changes:
        messages.success(request, "Exceções do usuário salvas. Já valem na próxima ação dele.")
    else:
        messages.info(request, "Nenhuma alteração nas exceções.")
    return redirect(f"{reverse('team:permissions')}?aba={target.role.lower()}&usuario={target.pk}#excecoes")
