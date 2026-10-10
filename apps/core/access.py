"""Escopo hierárquico de dados. TODA consulta a eleitores/equipe deve passar por aqui.

  - ADMIN:        toda a campanha
  - COORDENADOR:  ele mesmo + cabos diretamente abaixo dele (parent = coordenador)
  - CABO:         apenas ele mesmo

O isolamento entre campanhas é garantido por `campaign_id` em todos os filtros. Os helpers aceitam qualquer
objeto com `id`, `role` e `campaign_id` (inclusive no worker, fora de requisições).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db.models import Q, QuerySet

from .constants import Role
from .phone import normalize_br_phone

SAO_PAULO = ZoneInfo("America/Sao_Paulo")

# Eleitores aptos a receber disparos: consentiram e não pediram descadastro
MESSAGEABLE_Q = Q(whatsapp_opt_in=True, opt_out_at__isnull=True, consent_at__isnull=False)


def scope_user_ids(user) -> list | None:
    """Ids dos usuários cuja rede o usuário enxerga; None = campanha inteira (ADMIN)."""
    from apps.accounts.models import User

    if user.role == Role.ADMIN:
        return None
    if user.role == Role.COORDENADOR:
        children = User.objects.filter(campaign_id=user.campaign_id, parent_id=user.id).values_list("id", flat=True)
        return [user.id, *children]
    return [user.id]


def voter_scope(user) -> QuerySet:
    """Eleitores visíveis ao usuário (SEMPRE comece por aqui)."""
    from apps.voters.models import Voter

    if user.campaign_id is None or user.role == Role.SUPER_ADMIN:
        return Voter.objects.none()
    qs = Voter.objects.filter(campaign_id=user.campaign_id)
    ids = scope_user_ids(user)
    return qs if ids is None else qs.filter(registered_by_id__in=ids)


def team_scope(user) -> QuerySet:
    """Membros da equipe visíveis ao usuário."""
    from apps.accounts.models import User

    if user.campaign_id is None or user.role == Role.SUPER_ADMIN:
        return User.objects.none()
    qs = User.objects.filter(campaign_id=user.campaign_id)
    if user.role == Role.ADMIN:
        return qs
    if user.role == Role.COORDENADOR:
        return qs.filter(Q(id=user.id) | Q(parent_id=user.id))
    return qs.filter(id=user.id)


def get_voter_in_scope(user, voter_id) -> Any | None:
    """Um eleitor pelo id, se estiver no escopo do usuário (senão None)."""
    try:
        return voter_scope(user).filter(pk=voter_id).first()
    except (ValueError, TypeError, ValidationError):  # id malformado
        return None


def get_member_in_scope(user, member_id) -> Any | None:
    """Um membro da equipe pelo id, se estiver no escopo do usuário (senão None)."""
    try:
        return team_scope(user).filter(pk=member_id).first()
    except (ValueError, TypeError, ValidationError):
        return None


def can_access_member(user, member_id) -> bool:
    return get_member_in_scope(user, member_id) is not None


def _day_start(iso: str) -> dt.datetime:
    return dt.datetime.fromisoformat(iso).replace(tzinfo=SAO_PAULO)


def _day_end(iso: str) -> dt.datetime:
    return dt.datetime.fromisoformat(iso).replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=SAO_PAULO)


def _minus_years(d: dt.date, years: int) -> dt.date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:  # 29/02
        return d.replace(year=d.year - years, day=28)


def apply_voter_filters(qs: QuerySet, campaign_id, filters: Mapping[str, Any] | None) -> QuerySet:
    """Aplica filtros (apps.core.voter_filters) sobre um queryset de Voter. NÃO aplica escopo."""
    from apps.accounts.models import User
    from .voter_filters import sanitize_voter_filters

    f = sanitize_voter_filters(filters)
    if q := f.get("q"):
        digits = "".join(c for c in q if c.isdigit())
        cond = Q(name__icontains=q) | Q(email__icontains=q)
        if len(digits) >= 4:
            cond |= Q(phone__contains=digits)
            if (normalized := normalize_br_phone(digits)) is not None:
                cond |= Q(phone=normalized)
        qs = qs.filter(cond)
    if v := f.get("neighborhoods"):
        qs = qs.filter(neighborhood__in=v)
    if v := f.get("cities"):
        qs = qs.filter(city__in=v)
    if v := f.get("registered_by_ids"):
        qs = qs.filter(registered_by_id__in=v)
    if v := f.get("coordinator_ids"):
        cabos = User.objects.filter(campaign_id=campaign_id, parent_id__in=v).values_list("id", flat=True)
        qs = qs.filter(Q(registered_by_id__in=v) | Q(registered_by_id__in=list(cabos)))
    if v := f.get("genders"):
        qs = qs.filter(gender__in=v)
    if v := f.get("support_levels"):
        qs = qs.filter(support_level__in=v)
    if v := f.get("sources"):
        qs = qs.filter(source__in=v)
    if v := f.get("electoral_zones"):
        qs = qs.filter(electoral_zone__in=v)
    if v := f.get("tags"):
        cond = Q()
        for tag in v:
            cond |= Q(tags__contains=f",{tag},")
        qs = qs.filter(cond)
    today = dt.datetime.now(SAO_PAULO).date()
    if (age_min := f.get("age_min")) is not None:  # idade >= min  ⇔  nascimento <= hoje - min anos
        qs = qs.filter(birth_date__lte=_minus_years(today, age_min))
    if (age_max := f.get("age_max")) is not None:  # idade <= max  ⇔  nascimento > hoje - (max+1) anos
        qs = qs.filter(birth_date__gt=_minus_years(today, age_max + 1))
    if v := f.get("created_from"):
        qs = qs.filter(created_at__gte=_day_start(v))
    if v := f.get("created_to"):
        qs = qs.filter(created_at__lte=_day_end(v))
    if f.get("has_geo") is True:
        qs = qs.filter(latitude__isnull=False, longitude__isnull=False)
    elif f.get("has_geo") is False:
        qs = qs.filter(Q(latitude__isnull=True) | Q(longitude__isnull=True))
    if f.get("messageable") is True:
        qs = qs.filter(MESSAGEABLE_Q)
    return qs


def voters_queryset(user, filters: Mapping[str, Any] | None = None) -> QuerySet:
    """Eleitores = escopo do usuário AND filtros. Filtros nunca ampliam o escopo."""
    return apply_voter_filters(voter_scope(user), user.campaign_id, filters)
