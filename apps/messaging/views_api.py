"""Endpoints JSON/automação do módulo: contagem do público do assistente e tick da fila (cron)."""

from __future__ import annotations

import hmac
import logging

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from apps.core.access import voters_queryset
from apps.core.decorators import module_permission_required
from apps.core.http import json_error
from apps.core.ratelimit import rate_limit
from apps.core.template_vars import build_template_context, render_template
from apps.core.utils import client_ip, first_name
from apps.core.voter_filters import parse_voter_filters

from .logic import MAX_RATE_PER_MINUTE, estimate_duration_minutes, format_duration
from .processor import DEFAULT_MAX_MESSAGES, run_queue_tick
from .queries import audience_counts, describe_filters, get_template_in_campaign, team_ids_in_scope

logger = logging.getLogger(__name__)

SAMPLE_COUNT = 3


@module_permission_required("disparos", "create", json_response=True)
@require_GET
@never_cache
def audience_api(request):
    """Quebra do público do assistente. Filtros na querystring (mesmos parâmetros da lista de apoiadores). Sempre
    limitado ao escopo de quem consulta; `messageable` é ignorado (o resultado já separa quem pode receber).

    Com `detalhe=1` devolve também: resumo dos filtros, duração estimada (`velocidade`) e até 3 mensagens de exemplo
    renderizadas com o modelo (`modelo`).
    """
    user = request.user
    throttle = rate_limit(f"audience:{user.pk}", 120, 60)
    if not throttle.ok:
        return json_error("Muitas consultas seguidas. Aguarde alguns segundos.", status=429)

    filters = parse_voter_filters(request.GET)
    filters.pop("messageable", None)
    if not team_ids_in_scope(user, filters):
        return json_error("Os filtros de equipe selecionados não pertencem à sua rede.", status=400)

    counts = audience_counts(user, filters)
    payload = dict(counts)

    if request.GET.get("detalhe") == "1":
        payload["filters_summary"] = [{"label": label, "value": value} for label, value in describe_filters(filters, user.campaign_id)]
        rate = _int_param(request.GET.get("velocidade"), 1, MAX_RATE_PER_MINUTE)
        minutes = estimate_duration_minutes(counts["eligible"], rate) if rate else 0
        payload["duration_minutes"] = minutes
        payload["duration_label"] = format_duration(minutes)
        payload["samples"] = _samples(request, filters)
    return JsonResponse(payload)


def _int_param(value, low: int, high: int) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


def _samples(request, filters: dict) -> list[dict]:
    """Mensagens de exemplo (modelo + apoiadores reais do público, no escopo do usuário). Só o primeiro nome sai."""
    template = get_template_in_campaign(request.user, request.GET.get("modelo"))
    if template is None:
        return []
    voters = (
        voters_queryset(request.user, {**filters, "messageable": True})
        .select_related("registered_by")
        .order_by("name", "id")[:SAMPLE_COUNT]
    )
    return [
        {
            "name": first_name(voter.name),
            "body": render_template(template.body, build_template_context(voter, request.campaign, voter.registered_by)),
        }
        for voter in voters
    ]


# --------------------------------------------------------------------------------------------- cron


def _cron_credential(request) -> str:
    header = request.headers.get("Authorization", "")
    if header[:7].lower() == "bearer ":
        return header[7:].strip()
    return (request.GET.get("secret") or "").strip()


@csrf_exempt
@require_http_methods(["GET", "POST"])
@never_cache
def cron_tick(request):
    """Executa um ciclo global da fila (para agendadores externos quando o worker não está rodando).
    Autenticação: `Authorization: Bearer <CRON_SECRET>` ou `?secret=<CRON_SECRET>`."""
    expected = getattr(settings, "CRON_SECRET", "") or ""
    if not expected:
        return JsonResponse({"error": "CRON_SECRET não configurado no servidor."}, status=503)

    ip = client_ip(request)
    if not rate_limit(f"cron-fail-check:{ip}", 120, 60).ok:
        return JsonResponse({"error": "Muitas requisições."}, status=429)

    provided = _cron_credential(request)
    if not provided or not hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
        return JsonResponse({"error": "Não autorizado."}, status=401)

    report = run_queue_tick(max_messages=DEFAULT_MAX_MESSAGES)
    return JsonResponse(report)
