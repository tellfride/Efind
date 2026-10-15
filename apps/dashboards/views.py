"""Views dos dashboards personalizáveis (/painel/ e /painel/dashboards/**).

Toda view começa com um decorator de `apps.core.decorators`; dashboards só são buscados por
`services.get_visible_dashboard` (mesma campanha E (compartilhado OU dono)), nunca por `objects.get(pk=...)`.
Mudanças de estado: apenas POST + CSRF + auditoria.
"""

from __future__ import annotations

import json
import logging

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from apps.auditlog.service import audit
from apps.core.constants import Role
from apps.core.decorators import admin_required, campaign_user_required, module_permission_required
from apps.core.filter_options import get_voter_filter_options
from apps.core.http import json_error
from apps.core.nav import first_accessible_path
from apps.core.permissions import can
from apps.core.ratelimit import rate_limit
from apps.core.utils import first_name
from apps.core.voter_filters import parse_voter_filters

from . import rules, services
from .data import compute_dashboard_data
from .forms import DashboardCreateForm, DashboardSaveForm
from .models import Dashboard
from .presets import DASHBOARD_PRESETS, preset_widgets
from .widgets import (
    MAX_NOTE_LENGTH,
    MAX_WIDGET_TITLE,
    MAX_WIDGETS,
    WIDGET_GROUPS,
    WIDGET_PERIOD_LABELS,
    WIDGET_SIZE_LABELS,
    catalog_for_client,
    icon_names,
    parse_stored_widgets,
    validate_widgets,
)

logger = logging.getLogger(__name__)

DATA_RATE_LIMIT = (120, 60)  # requisições por janela (segundos) e por usuário
AUTO_REFRESH_SECONDS = 120
PREVIEW_PRESET = "visao_geral"
NETWORK_ROLES = (Role.COORDENADOR, Role.CABO)


# ---------------------------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------------------------


def _visible_or_404(request, pk) -> Dashboard:
    dashboard = services.get_visible_dashboard(request.user, request.perms, pk)
    if dashboard is None:
        raise Http404("Dashboard não encontrado.")
    return services.annotate_dashboard(request.user, request.perms, dashboard)


def _safe_next(request, fallback: str) -> str:
    target = request.POST.get("next") or ""
    if target.startswith("/painel/") and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return target
    return fallback


def _js_config(request, widgets: list[dict], **extra) -> dict:
    return {
        "widgets": widgets,
        "catalog": catalog_for_client(request.perms),
        "dataUrl": reverse("dashboards:data"),
        "csrf": get_token(request),
        "editable": False,
        "autoRefresh": AUTO_REFRESH_SECONDS,
        "periods": [{"value": v, "label": label} for v, label in WIDGET_PERIOD_LABELS.items()],
        "sizes": [{"value": k, **v} for k, v in WIDGET_SIZE_LABELS.items()],
        "groups": [{"key": k, "label": label} for k, label in WIDGET_GROUPS],
        **extra,
    }


def _viewer_context(request, *, dashboard: Dashboard | None, widgets: list[dict], dashboards: list[Dashboard], **extra) -> dict:
    user = request.user
    can_edit = bool(dashboard and dashboard.can_edit)
    can_personalize = bool(dashboard and not can_edit and dashboard.can_duplicate)
    return {
        "dashboard": dashboard,
        "widgets": widgets,
        "dashboards": dashboards,
        "first_name": first_name(user.name),
        "network_hint": user.role in NETWORK_ROLES,
        "can_edit": can_edit,
        "can_personalize": can_personalize,
        "can_create": can(request.perms, "dashboard", "create"),
        "dash_config": _js_config(request, widgets),
        "icon_names": icon_names(),
        **extra,
    }


# ---------------------------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------------------------


@never_cache
@campaign_user_required
def home(request):
    """/painel/ — meu padrão → padrão da campanha → primeiro visível (ou o modelo "Visão geral" só para leitura)."""
    user, perms = request.user, request.perms
    if not can(perms, "dashboard", "view"):
        return redirect(first_accessible_path(user, perms))

    dashboards = [services.annotate_dashboard(user, perms, d) for d in services.list_visible_dashboards(user, perms)]
    current = rules.pick_home_dashboard(dashboards, user.pk)
    if current is not None:
        widgets = parse_stored_widgets(current.widgets)
        return render(
            request,
            "dashboards/detail.html",
            _viewer_context(request, dashboard=current, widgets=widgets, dashboards=dashboards, is_home=True),
        )

    # Campanha sem nenhum dashboard: o ADMIN cria os padrões; os demais veem o modelo em modo leitura (não é salvo)
    if user.role == Role.ADMIN:
        return render(
            request,
            "dashboards/home_empty.html",
            {
                "can_create": can(perms, "dashboard", "create"),
                "can_create_defaults": not services.campaign_has_dashboards(user.campaign_id),
            },
        )
    widgets = preset_widgets(PREVIEW_PRESET)
    return render(
        request,
        "dashboards/detail.html",
        _viewer_context(
            request,
            dashboard=None,
            widgets=widgets,
            dashboards=[],
            is_home=True,
            preview=DASHBOARD_PRESETS[PREVIEW_PRESET],
        ),
    )


@never_cache
@module_permission_required("dashboard", "view")
def dashboard_list(request):
    user, perms = request.user, request.perms
    dashboards = [services.annotate_dashboard(user, perms, d) for d in services.list_visible_dashboards(user, perms)]
    return render(
        request,
        "dashboards/list.html",
        {
            "dashboards": dashboards,
            "shared_dashboards": [d for d in dashboards if d.shared],
            "my_dashboards": [d for d in dashboards if not d.shared],
            "can_create": can(perms, "dashboard", "create"),
            "can_create_defaults": (
                user.role == Role.ADMIN and not dashboards and not services.campaign_has_dashboards(user.campaign_id)
            ),
            "is_admin": user.role == Role.ADMIN,
            "network_hint": user.role in NETWORK_ROLES,
        },
    )


@never_cache
@module_permission_required("dashboard", "view")
def detail(request, pk):
    dashboard = _visible_or_404(request, pk)
    dashboards = [services.annotate_dashboard(request.user, request.perms, d) for d in services.list_visible_dashboards(request.user, request.perms)]
    widgets = parse_stored_widgets(dashboard.widgets)
    return render(
        request,
        "dashboards/detail.html",
        _viewer_context(request, dashboard=dashboard, widgets=widgets, dashboards=dashboards, is_home=False),
    )


@module_permission_required("dashboard", "create")
def create(request):
    """Novo dashboard: nome, descrição e ponto de partida (um dos modelos ou em branco)."""
    form = DashboardCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            dashboard = services.create_dashboard(
                request.user, name=data["name"], description=data["description"], preset=data["preset"]
            )
        except services.DashboardLimitError as exc:
            form.add_error(None, str(exc))
        else:
            audit(
                "dashboard.create",
                request=request,
                entity="Dashboard",
                entity_id=dashboard.pk,
                details={"name": dashboard.name, "preset": data["preset"], "widgets": len(dashboard.widgets)},
            )
            messages.success(request, "Dashboard criado.")
            can_edit = rules.can_edit(request.user, request.perms, dashboard)
            return redirect("dashboards:edit" if can_edit else "dashboards:detail", pk=dashboard.pk)
    return render(
        request,
        "dashboards/create.html",
        {"form": form, "presets": services.preset_catalog(), "selected_preset": form["preset"].value() or services.BLANK_PRESET},
    )


@never_cache
@module_permission_required("dashboard", "view")
def edit(request, pk):
    """Montador: adicionar, configurar, reordenar e remover widgets, com pré-visualização dos dados reais."""
    user, perms = request.user, request.perms
    dashboard = _visible_or_404(request, pk)
    if not dashboard.can_edit:
        raise PermissionDenied("Você não tem permissão para editar este dashboard.")
    widgets = parse_stored_widgets(dashboard.widgets)
    is_admin = rules.can_share(user)
    config = _js_config(
        request,
        widgets,
        editable=True,
        autoRefresh=0,
        saveUrl=reverse("dashboards:save", args=[dashboard.pk]),
        filtersUrl=reverse("dashboards:filters"),
        detailUrl=reverse("dashboards:detail", args=[dashboard.pk]),
        listUrl=reverse("dashboards:list"),
        isAdmin=is_admin,
        limits={"widgets": MAX_WIDGETS, "note": MAX_NOTE_LENGTH, "title": MAX_WIDGET_TITLE},
        dashboard={
            "name": dashboard.name,
            "description": dashboard.description,
            "shared": dashboard.shared,
            "campaignDefault": dashboard.is_campaign_default,
        },
    )
    return render(
        request,
        "dashboards/edit.html",
        {
            "dashboard": dashboard,
            "widgets": widgets,
            "is_admin": is_admin,
            "dash_config": config,
            "icon_names": icon_names(),
            "max_title": MAX_WIDGET_TITLE,
            "max_note": MAX_NOTE_LENGTH,
        },
    )


# ---------------------------------------------------------------------------------------------
# Ações (POST + redirect)
# ---------------------------------------------------------------------------------------------


@require_POST
@module_permission_required("dashboard", "create")
def duplicate(request, pk):
    source = _visible_or_404(request, pk)
    if not source.can_duplicate:
        raise PermissionDenied
    try:
        copy_ = services.duplicate_dashboard(request.user, source)
    except services.DashboardLimitError as exc:
        messages.error(request, str(exc))
        return redirect(_safe_next(request, reverse("dashboards:list")))
    audit(
        "dashboard.create",
        request=request,
        entity="Dashboard",
        entity_id=copy_.pk,
        details={"name": copy_.name, "duplicated_from": str(source.pk), "widgets": len(copy_.widgets)},
    )
    if request.POST.get("then") == "edit" and rules.can_edit(request.user, request.perms, copy_):
        messages.success(request, "Criamos uma cópia só sua. Personalize os widgets e salve.")
        return redirect("dashboards:edit", pk=copy_.pk)
    messages.success(request, "Dashboard duplicado.")
    return redirect("dashboards:list")


@require_POST
@module_permission_required("dashboard", "view")
def toggle_default(request, pk):
    """Define (ou remove) "meu padrão": o dashboard aberto ao entrar no painel. Um por usuário."""
    dashboard = _visible_or_404(request, pk)
    if not dashboard.can_set_my_default:
        raise PermissionDenied("Apenas dashboards seus e não compartilhados podem ser o seu padrão.")
    now_default = services.toggle_my_default(request.user, dashboard)
    audit(
        "dashboard.update",
        request=request,
        entity="Dashboard",
        entity_id=dashboard.pk,
        details={"name": dashboard.name, "my_default": now_default},
    )
    messages.success(
        request,
        "Este agora é o seu dashboard inicial." if now_default else "O dashboard deixou de ser o seu padrão.",
    )
    return redirect(_safe_next(request, reverse("dashboards:list")))


@require_POST
@module_permission_required("dashboard", "view")
def delete(request, pk):
    dashboard = _visible_or_404(request, pk)
    if not dashboard.can_delete:
        raise PermissionDenied("Você não tem permissão para excluir este dashboard.")
    details = {"name": dashboard.name, "shared": dashboard.shared, "default": dashboard.is_default}
    dashboard_id = dashboard.pk
    services.delete_dashboard(dashboard)
    audit("dashboard.delete", request=request, entity="Dashboard", entity_id=dashboard_id, details=details)
    messages.success(request, "Dashboard excluído.")
    return redirect("dashboards:list")


@require_POST
@admin_required
def create_defaults(request):
    """O ADMIN cria os dashboards-modelo da campanha (somente se ela ainda não tiver nenhum)."""
    if services.create_default_dashboards_if_none(request.campaign):
        audit("dashboard.create", request=request, entity="Dashboard", details={"defaults": True})
        messages.success(request, "Dashboards padrão criados.")
    else:
        messages.info(request, "A campanha já possui dashboards.")
    return redirect("dashboards:home")


# ---------------------------------------------------------------------------------------------
# API JSON
# ---------------------------------------------------------------------------------------------


def _json_body(request) -> dict | None:
    try:
        body = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return body if isinstance(body, dict) else None


def _first_message(exc: ValidationError) -> str:
    return exc.messages[0] if exc.messages else "Dados inválidos."


@never_cache
@module_permission_required("dashboard", "view", json_response=True)
@require_POST
def data(request):
    """POST {"widgets": [...]} → {id_do_widget: dados | {"error": "..."}}, sempre no escopo do usuário logado."""
    limit, window = DATA_RATE_LIMIT
    if not rate_limit(f"dash-data:{request.user.pk}", limit, window).ok:
        return json_error("Muitas atualizações seguidas. Aguarde um instante.", 429)
    body = _json_body(request)
    if body is None:
        return json_error("Requisição inválida.")
    try:
        widgets = validate_widgets(body.get("widgets"))
    except ValidationError as exc:
        return json_error(_first_message(exc))
    return JsonResponse(compute_dashboard_data(request.user, widgets, perms=request.perms))


@never_cache
@module_permission_required("dashboard", "view", json_response=True)
def filters_panel(request):
    """Fragmento HTML com o painel de filtros de apoiadores (opções no escopo do usuário) para o modal do widget."""
    return render(
        request,
        "dashboards/_filters.html",
        {
            "filters": parse_voter_filters(request.GET),
            "filter_options": get_voter_filter_options(request.user),
            "filter_action": reverse("dashboards:filters"),
            "filter_hide": ["q"],
        },
    )


@never_cache
@module_permission_required("dashboard", "view", json_response=True)
@require_POST
def save(request, pk):
    """Salva o dashboard do montador: {name, description, shared, campaign_default, widgets}."""
    user, perms = request.user, request.perms
    dashboard = services.get_visible_dashboard(user, perms, pk)
    if dashboard is None:
        return json_error("Dashboard não encontrado.", 404)
    if not rules.can_edit(user, perms, dashboard):
        return json_error("Você não tem permissão para editar este dashboard.", 403)

    body = _json_body(request)
    if body is None:
        return json_error("Requisição inválida.")
    form = DashboardSaveForm(body)
    if not form.is_valid():
        return json_error(form.first_error())
    try:
        widgets = validate_widgets(body.get("widgets"))
    except ValidationError as exc:
        return json_error(_first_message(exc))
    widgets = services.restrict_filters_to_scope(user, widgets)

    cleaned = form.cleaned_data
    saved = services.save_dashboard(
        user,
        dashboard,
        name=cleaned["name"],
        description=cleaned["description"],
        shared=cleaned["shared"],
        campaign_default=cleaned["campaign_default"],
        widgets=widgets,
    )
    audit(
        "dashboard.update",
        request=request,
        entity="Dashboard",
        entity_id=saved.pk,
        details={
            "name": saved.name,
            "widgets": len(widgets),
            "shared": saved.shared,
            "campaign_default": rules.is_campaign_default(saved),
        },
    )
    still_visible = bool(saved.shared or saved.owner_id == user.pk)
    return JsonResponse(
        {
            "ok": True,
            "message": "Dashboard salvo.",
            "widgets": widgets,
            "dashboard": {
                "name": saved.name,
                "description": saved.description,
                "shared": saved.shared,
                "campaignDefault": rules.is_campaign_default(saved),
            },
            "redirect": None if still_visible else reverse("dashboards:list"),
        }
    )
