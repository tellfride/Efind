"""Operações sobre dashboards (consulta com visibilidade + escritas transacionais).

As views chamam estes serviços depois de checar a permissão do módulo; a visibilidade e as regras de edição vêm de
`rules.py`. Nunca busque `Dashboard.objects.get(pk=...)` solto: use `get_visible_dashboard`.
"""

from __future__ import annotations

import copy

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from apps.core.access import team_scope
from apps.core.permissions import can

from . import rules
from .models import Dashboard
from .presets import DASHBOARD_PRESET_KEYS, DASHBOARD_PRESETS, create_default_dashboards, preset_widgets
from .widgets import parse_stored_widgets

MAX_OWN_DASHBOARDS = 50
BLANK_PRESET = "blank"
SCOPED_FILTER_KEYS = ("registered_by_ids", "coordinator_ids")


class DashboardLimitError(Exception):
    """O usuário já tem o máximo de dashboards próprios."""


def visible_queryset(user):
    """Dashboards da campanha do usuário que ele pode ver (compartilhados + próprios)."""
    if user.campaign_id is None:
        return Dashboard.objects.none()
    return Dashboard.objects.filter(campaign_id=user.campaign_id).filter(Q(shared=True) | Q(owner_id=user.pk))


def list_visible_dashboards(user, perms) -> list[Dashboard]:
    """Dashboards visíveis, já ordenados (padrão da campanha, meu padrão, compartilhados, próprios)."""
    if not can(perms, "dashboard", "view"):
        return []
    rows = list(visible_queryset(user).select_related("owner").order_by("created_at")[:300])
    return rules.sort_dashboards(rows, user.pk)


def get_visible_dashboard(user, perms, pk) -> Dashboard | None:
    """Um dashboard visível ao usuário (senão None — a view responde 404). Aceita ids malformados."""
    if not can(perms, "dashboard", "view"):
        return None
    try:
        return visible_queryset(user).select_related("owner").filter(pk=pk).first()
    except (ValueError, TypeError, ValidationError):
        return None


def annotate_dashboard(user, perms, dashboard: Dashboard) -> Dashboard:
    """Anexa ao dashboard os flags usados pelos templates (permissões e selos)."""
    dashboard.widget_count = len(parse_stored_widgets(dashboard.widgets))
    dashboard.is_mine = dashboard.owner_id == user.pk
    dashboard.is_campaign_default = rules.is_campaign_default(dashboard)
    dashboard.is_my_default = rules.is_personal_default(dashboard, user.pk)
    dashboard.can_edit = rules.can_edit(user, perms, dashboard)
    dashboard.can_delete = rules.can_delete(user, perms, dashboard)
    dashboard.can_duplicate = rules.can_duplicate(user, perms, dashboard)
    dashboard.can_set_my_default = rules.can_set_my_default(user, perms, dashboard)
    return dashboard


def preset_catalog() -> list[dict]:
    """Modelos de dashboard oferecidos em "Novo dashboard" (com a quantidade de widgets)."""
    return [
        {
            "key": key,
            "name": DASHBOARD_PRESETS[key]["name"],
            "description": DASHBOARD_PRESETS[key]["description"],
            "widget_count": len(DASHBOARD_PRESETS[key]["widgets"]),
        }
        for key in DASHBOARD_PRESET_KEYS
    ]


def _ensure_own_limit(user) -> None:
    if Dashboard.objects.filter(campaign_id=user.campaign_id, owner_id=user.pk).count() >= MAX_OWN_DASHBOARDS:
        raise DashboardLimitError(f"Você já tem {MAX_OWN_DASHBOARDS} dashboards. Exclua algum antes de criar outro.")


def create_dashboard(user, *, name: str, description: str = "", preset: str = BLANK_PRESET) -> Dashboard:
    """Cria um dashboard próprio (não compartilhado), em branco ou a partir de um modelo."""
    _ensure_own_limit(user)
    widgets = preset_widgets(preset) if preset in DASHBOARD_PRESET_KEYS else []
    return Dashboard.objects.create(
        campaign_id=user.campaign_id,
        owner=user,
        name=name,
        description=description,
        shared=False,
        is_default=False,
        widgets=widgets,
    )


def duplicate_dashboard(user, source: Dashboard) -> Dashboard:
    """Cópia própria e privada de um dashboard visível."""
    _ensure_own_limit(user)
    return Dashboard.objects.create(
        campaign_id=user.campaign_id,
        owner=user,
        name=f"Cópia de {source.name}"[:120],
        description=source.description,
        shared=False,
        is_default=False,
        widgets=copy.deepcopy(parse_stored_widgets(source.widgets)),
    )


@transaction.atomic
def toggle_my_default(user, dashboard: Dashboard) -> bool:
    """Alterna "meu padrão" (um por dono). Devolve o novo valor."""
    new_value = not dashboard.is_default
    if new_value:
        Dashboard.objects.filter(
            campaign_id=user.campaign_id, owner_id=user.pk, shared=False, is_default=True
        ).exclude(pk=dashboard.pk).update(is_default=False)
    dashboard.is_default = new_value
    dashboard.save(update_fields=["is_default", "updated_at"])
    return new_value


def restrict_filters_to_scope(user, widgets: list[dict]) -> list[dict]:
    """Remove dos filtros dos widgets os ids de equipe fora da campanha/escopo de quem está salvando."""
    wanted: set[str] = set()
    for widget in widgets:
        filters = widget["config"].get("filters") or {}
        for key in SCOPED_FILTER_KEYS:
            wanted.update(filters.get(key, ()))
    if not wanted:
        return widgets
    allowed = {str(pk) for pk in team_scope(user).filter(pk__in=wanted).values_list("pk", flat=True)}
    for widget in widgets:
        filters = widget["config"].get("filters")
        if not filters:
            continue
        for key in SCOPED_FILTER_KEYS:
            if key in filters:
                kept = [v for v in filters[key] if v in allowed]
                if kept:
                    filters[key] = kept
                else:
                    del filters[key]
        if not filters:
            del widget["config"]["filters"]
    return widgets


@transaction.atomic
def save_dashboard(
    user,
    dashboard: Dashboard,
    *,
    name: str,
    description: str,
    shared: bool,
    campaign_default: bool,
    widgets: list[dict],
) -> Dashboard:
    """Grava nome, descrição, compartilhamento e widgets. Só o ADMIN altera compartilhamento/padrão da campanha."""
    sharing = rules.resolve_sharing(user, dashboard, shared=shared, campaign_default=campaign_default)
    if sharing["shared"] and sharing["is_default"]:  # exatamente um padrão da campanha
        Dashboard.objects.filter(campaign_id=user.campaign_id, shared=True, is_default=True).exclude(
            pk=dashboard.pk
        ).update(is_default=False)
    dashboard.name = name
    dashboard.description = description
    dashboard.shared = sharing["shared"]
    dashboard.is_default = sharing["is_default"]
    dashboard.owner_id = sharing["owner_id"]
    dashboard.widgets = widgets
    dashboard.save()
    return dashboard


def create_default_dashboards_if_none(campaign) -> bool:
    """Cria os dashboards-modelo da campanha somente se ela ainda não tiver nenhum. Devolve se criou."""
    with transaction.atomic():
        # bloqueia a linha da campanha para que dois cliques simultâneos não dupliquem os modelos
        from apps.campaigns.models import Campaign

        Campaign.objects.select_for_update().filter(pk=campaign.pk).first()
        if Dashboard.objects.filter(campaign_id=campaign.pk).exists():
            return False
        create_default_dashboards(campaign)
        return True


def campaign_has_dashboards(campaign_id) -> bool:
    """A campanha já tem algum dashboard (de qualquer pessoa)? Usado para oferecer "Criar dashboards padrão"."""
    return Dashboard.objects.filter(campaign_id=campaign_id).exists()


def delete_dashboard(dashboard: Dashboard) -> None:
    dashboard.delete()
