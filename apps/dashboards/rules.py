"""Regras de acesso aos dashboards (puras — funcionam com qualquer objeto que tenha os atributos usados).

  - Ver: mesma campanha + permissão dashboard.view + (compartilhado OU dono).
  - Editar/excluir: o ADMIN edita/exclui qualquer dashboard visível; os demais só os próprios dashboards NÃO
    compartilhados, com dashboard.edit / dashboard.delete. Dashboards compartilhados ou sem dono: somente ADMIN.
  - Padrão da campanha = compartilhado + is_default (exatamente um, definido pelo ADMIN).
  - "Meu padrão" = dashboard próprio, não compartilhado, com is_default (um por dono).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from apps.core.constants import Role
from apps.core.permissions import can


def is_visible(user, perms, dashboard) -> bool:
    if dashboard.campaign_id != user.campaign_id:
        return False
    if not can(perms, "dashboard", "view"):
        return False
    return bool(dashboard.shared or dashboard.owner_id == user.pk)


def _is_admin(user) -> bool:
    return user.role == Role.ADMIN


def can_edit(user, perms, dashboard) -> bool:
    if not is_visible(user, perms, dashboard):
        return False
    if _is_admin(user):
        return True
    return dashboard.owner_id == user.pk and not dashboard.shared and can(perms, "dashboard", "edit")


def can_delete(user, perms, dashboard) -> bool:
    if not is_visible(user, perms, dashboard):
        return False
    if _is_admin(user):
        return True
    return dashboard.owner_id == user.pk and not dashboard.shared and can(perms, "dashboard", "delete")


def can_duplicate(user, perms, dashboard) -> bool:
    return is_visible(user, perms, dashboard) and can(perms, "dashboard", "create")


def can_set_my_default(user, perms, dashboard) -> bool:
    """"Meu padrão" só vale para dashboards próprios e não compartilhados."""
    return is_visible(user, perms, dashboard) and dashboard.owner_id == user.pk and not dashboard.shared


def can_share(user) -> bool:
    """Somente o ADMIN define "compartilhado" e "padrão da campanha"."""
    return _is_admin(user)


def is_campaign_default(dashboard) -> bool:
    return bool(dashboard.shared and dashboard.is_default)


def is_personal_default(dashboard, user_id) -> bool:
    return bool(not dashboard.shared and dashboard.is_default and dashboard.owner_id == user_id)


def pick_home_dashboard(visible: Sequence[Any], user_id) -> Any | None:
    """Dashboard aberto em /painel/: meu padrão → padrão da campanha → primeiro visível."""
    for d in visible:
        if is_personal_default(d, user_id):
            return d
    for d in visible:
        if is_campaign_default(d):
            return d
    return visible[0] if visible else None


def sort_dashboards(dashboards: Sequence[Any], user_id) -> list[Any]:
    """Ordem da lista: padrão da campanha, meu padrão, compartilhados, próprios — e por nome."""

    def weight(d) -> int:
        if is_campaign_default(d):
            return 0
        if is_personal_default(d, user_id):
            return 1
        return 2 if d.shared else 3

    return sorted(dashboards, key=lambda d: (weight(d), d.name.casefold()))


def resolve_sharing(user, current, *, shared: bool, campaign_default: bool) -> dict[str, Any]:
    """Novo estado de compartilhamento ao salvar.

    Só o ADMIN altera "compartilhado" e "padrão da campanha"; para os demais o estado atual é mantido.
    Ao deixar de compartilhar um dashboard sem dono, o ADMIN passa a ser o dono (senão ninguém o veria).
    """
    if not _is_admin(user):
        return {"shared": current.shared, "is_default": current.is_default, "owner_id": current.owner_id}
    shared = bool(campaign_default or shared)
    if shared:
        return {"shared": True, "is_default": bool(campaign_default), "owner_id": current.owner_id}
    # Deixou de ser compartilhado: perde o "padrão da campanha", mas mantém "meu padrão" se já era pessoal
    keep_personal = not current.shared and current.is_default
    return {"shared": False, "is_default": keep_personal, "owner_id": current.owner_id or user.pk}
