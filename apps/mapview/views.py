"""Mapa territorial: página (/painel/mapa/), dados agregados em JSON e a ação do ADMIN de localizar pendentes."""

from __future__ import annotations

from urllib.parse import urlencode

from django.contrib import messages
from django.core.cache import cache
from django.http import JsonResponse, QueryDict
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_safe

from apps.auditlog.service import audit
from apps.core.constants import Role
from apps.core.decorators import admin_required, module_permission_required
from apps.core.filter_options import get_voter_filter_options
from apps.core.permissions import can
from apps.core.ratelimit import rate_limit
from apps.core.voter_filters import count_active_filters, parse_voter_filters, voter_filters_to_params

from .data import geo_queue_counts, load_map_data, map_filters
from .geocoding import DEFAULT_LIMIT, geocode_run_message, run_campaign_geocoding
from .options import build_map_config

VOTERS_URL = "/painel/eleitores/"
LOGIN_URL = "/login/"
# Filtros que não se aplicam ao mapa (ele já mostra quem tem e quem não tem localização)
HIDDEN_FILTERS = ["has_geo"]
GEOCODE_LOCK_SECONDS = 120


@module_permission_required("mapa")
@require_safe
def index(request):
    user = request.user
    filters = map_filters(parse_voter_filters(request.GET))
    is_admin = user.role == Role.ADMIN
    config = build_map_config(data_url=reverse("mapview:data"), voters_url=VOTERS_URL, login_url=LOGIN_URL)
    context = {
        "filters": filters,
        "filter_options": get_voter_filter_options(user),
        "hide_filters": HIDDEN_FILTERS,
        "active_filters": count_active_filters(filters),
        "filter_query": urlencode(voter_filters_to_params(filters)),
        "map_config": config,
        "is_admin": is_admin,
        "geo_queue": geo_queue_counts(user) if is_admin else None,
    }
    return render(request, "mapview/index.html", context)


@never_cache
@module_permission_required("mapa", json_response=True)
@require_GET
def data(request):
    """Dados agregados do mapa (bairros, pontos, limites) no escopo do usuário. Sem nomes nem telefones de eleitores."""
    filters = parse_voter_filters(request.GET)
    can_view_voters = can(request.perms, "eleitores", "view")
    return JsonResponse(load_map_data(request.user, filters, can_view_voters=can_view_voters))


def _back_to_map(request):
    """Volta ao mapa preservando os filtros. A querystring é reconstruída a partir dos filtros VALIDADOS,
    então nada vindo do formulário chega à URL de destino além de parâmetros de filtro conhecidos."""
    raw = (request.POST.get("qs") or "")[:2000]
    filters = map_filters(parse_voter_filters(QueryDict(raw)))
    query = urlencode(voter_filters_to_params(filters))
    base = reverse("mapview:index")
    return redirect(f"{base}?{query}" if query else base)


@admin_required
@require_POST
def geocode_pending(request):
    """ADMIN: devolve os FAILED da campanha à fila e processa até 15 eleitores agora."""
    user = request.user
    limit = rate_limit(f"mapview-geocode:{user.campaign_id}", 12, 10 * 60)
    if not limit.ok:
        messages.error(request, f"Muitas solicitações seguidas. Tente novamente em {max(1, limit.retry_after_seconds // 60)} min.")
        return _back_to_map(request)

    lock_key = f"mapview:geocode:{user.campaign_id}"
    if not cache.add(lock_key, 1, GEOCODE_LOCK_SECONDS):  # evita duas rodadas simultâneas da mesma campanha
        messages.warning(request, "Já existe uma localização em andamento. Aguarde alguns instantes.")
        return _back_to_map(request)
    try:
        result = run_campaign_geocoding(user, DEFAULT_LIMIT)
    finally:
        cache.delete(lock_key)

    audit(
        "voter.geocode",
        request=request,
        entity="Voter",
        details={
            "processed": result.processed,
            "located": result.located,
            "failed": result.failed,
            "remaining": result.remaining,
        },
    )
    level, text = geocode_run_message(result)
    getattr(messages, level)(request, text)
    return _back_to_map(request)
