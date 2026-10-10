"""Serviços de conta: permissões efetivas, criação de usuários e regras da hierarquia."""

from __future__ import annotations

from apps.core.constants import Role
from apps.core.permissions import PermissionSet, resolve_permissions

from .models import RolePermission, User, UserPermission


def permissions_for(user) -> PermissionSet:
    """Permissões efetivas do usuário (padrão do papel → matriz da campanha → exceções do usuário).
    Consulta o banco a cada chamada; o middleware guarda o resultado em request.perms."""
    if not getattr(user, "is_authenticated", False):
        return resolve_permissions(Role.SUPER_ADMIN)  # nada
    if user.role in (Role.ADMIN, Role.SUPER_ADMIN):
        return resolve_permissions(user.role)
    role_rows = [r.as_row() for r in RolePermission.objects.filter(campaign_id=user.campaign_id, role=user.role)]
    user_rows = [r.as_row() for r in UserPermission.objects.filter(user_id=user.pk)]
    return resolve_permissions(user.role, role_rows, user_rows)


def email_in_use(email: str, exclude_pk=None) -> bool:
    qs = User.objects.filter(email__iexact=email.strip())
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.exists()
