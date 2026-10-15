"""Consultas auxiliares da equipe. Todas recebem o `campaign_id` do usuário logado (nunca um id do cliente)."""

from __future__ import annotations

from django.core.exceptions import ValidationError

from apps.accounts.models import User
from apps.core.constants import Role
from apps.voters.models import Voter


def other_active_admins(campaign_id, exclude_pk) -> int:
    """Administradores ativos da campanha, exceto `exclude_pk`."""
    return User.objects.filter(campaign_id=campaign_id, role=Role.ADMIN, is_active=True).exclude(pk=exclude_pk).count()


def has_active_coordinators(campaign_id, exclude_pk=None) -> bool:
    qs = User.objects.filter(campaign_id=campaign_id, role=Role.COORDENADOR, is_active=True)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    return qs.exists()


def parent_candidates(campaign_id) -> list[User]:
    """Administradores e coordenadores da campanha (possíveis superiores), ordenados por nome."""
    return list(
        User.objects.filter(campaign_id=campaign_id, role__in=[Role.ADMIN, Role.COORDENADOR]).order_by("name")
    )


def get_campaign_user(campaign_id, user_id, roles=None) -> User | None:
    """Usuário da campanha pelo id (None se não existir, for de outra campanha, tiver papel fora de `roles` ou o
    id for malformado)."""
    if not user_id:
        return None
    qs = User.objects.filter(campaign_id=campaign_id)
    if roles is not None:
        qs = qs.filter(role__in=list(roles))
    try:
        return qs.filter(pk=user_id).first()
    except (ValueError, TypeError, ValidationError):
        return None


def voters_count(campaign_id, member_pk) -> int:
    """Apoiadores cadastrados pelo membro (contagem real, independente do escopo de visualização)."""
    return Voter.objects.filter(campaign_id=campaign_id, registered_by_id=member_pk).count()


def children_count(campaign_id, member_pk) -> int:
    return User.objects.filter(campaign_id=campaign_id, parent_id=member_pk).count()
