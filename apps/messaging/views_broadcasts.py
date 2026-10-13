"""Disparos de WhatsApp (/painel/mensagens/disparos/): lista, assistente, detalhe e ações.

Toda consulta passa por `broadcast_scope(user)` (ADMIN vê os disparos da campanha; os demais, só os que criaram) e
`template_scope(user)`. Modelo e conexão recebidos do cliente são sempre validados contra a campanha (BroadcastForm).
Mudanças de status são atualizações condicionais (`status__in=...`) para não sobrescrever pausa/cancelamento
concorrentes do worker.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.views.decorators.vary import vary_on_headers

from apps.auditlog.service import audit
from apps.core.access import voter_scope
from apps.core.constants import BroadcastStatus, MessageStatus, Role, label_of
from apps.core.decorators import admin_required, module_permission_required
from apps.core.filter_options import get_voter_filter_options
from apps.core.permissions import can
from apps.core.phone import format_phone
from apps.core.ratelimit import rate_limit
from apps.core.template_vars import EXAMPLE_CONTEXT, TEMPLATE_VARIABLES, render_template
from apps.core.voter_filters import sanitize_voter_filters
from apps.whatsapp import registry

from .counters import load_status_counts, refresh_broadcast_counters
from .display import BROADCAST_TONES, MEDIA_LABELS, decorate_broadcasts, mask_phone
from .forms import BroadcastForm
from .logic import (
    CONTROLS,
    DEFAULT_RATE_PER_MINUTE,
    MAX_MANUAL_ATTEMPTS,
    allowed_from,
    available_actions,
    broadcast_rates,
    can_delete_broadcast,
    format_duration,
    next_broadcast_status,
    percent,
    to_local_input,
)
from .models import Broadcast, BroadcastMessage, MessageTemplate
from .processor import materialize_broadcast, run_queue_tick
from .queries import (
    broadcast_scope,
    broadcast_send_problem,
    connected_connections,
    describe_filters,
    get_broadcast_in_scope,
    template_scope,
)

logger = logging.getLogger(__name__)

RECEIPTS_POLL_WINDOW = timedelta(minutes=30)  # após concluir, segue atualizando p/ mostrar entregas e leituras

BASE_URL = "/painel/mensagens/disparos/"
LIST_PER_PAGE = 20
RECIPIENTS_PER_PAGE = 50
#: Janela em que um disparo igual (mesmo nome e modelo, mesmo usuário) é tratado como reenvio do formulário
DUPLICATE_WINDOW_SECONDS = 30
#: Etapa do assistente que mostra o erro de cada campo do servidor
STEP_OF_FIELD = {
    "name": 0,
    "template": 0,
    "filters": 1,
    "connection": 2,
    "rate_per_minute": 2,
    "mode": 2,
    "scheduled_at": 2,
    "consent": 3,
    "__all__": 3,
}


def _detail_url(broadcast) -> str:
    return f"{BASE_URL}{broadcast.pk}/"


def _broadcast_or_404(request, pk) -> Broadcast:
    broadcast = get_broadcast_in_scope(request.user, pk)
    if broadcast is None:
        raise Http404("Disparo não encontrado.")
    return broadcast


# --------------------------------------------------------------------------------------------- lista


@module_permission_required("disparos", "view")
@never_cache
@vary_on_headers("HX-Request")
def broadcast_list(request):
    user = request.user
    status = request.GET.get("status") or ""
    base = broadcast_scope(user)
    queryset = base.select_related("template", "connection", "created_by")
    if status in BroadcastStatus.values:
        queryset = queryset.filter(status=status)
    else:
        status = ""

    page = Paginator(queryset.order_by("-created_at"), LIST_PER_PAGE).get_page(request.GET.get("page"))
    items = decorate_broadcasts(page.object_list)
    counts = {row["status"]: row["n"] for row in base.order_by().values("status").annotate(n=Count("id"))}
    context = {
        "page_obj": page,
        "broadcasts": items,
        "status": status,
        "status_options": [(value, label, counts.get(value, 0)) for value, label in BroadcastStatus.choices if value != BroadcastStatus.DRAFT],
        "total_in_scope": sum(counts.values()),
        "has_live": any(b.is_live for b in items),
        "is_admin": user.role == Role.ADMIN,
        "can_create": can(request.perms, "disparos", "create"),
        "refresh_url": request.get_full_path(),
    }
    if request.headers.get("HX-Request"):
        return render(request, "messaging/_broadcast_list_live.html", context)
    return render(request, "messaging/broadcast_list.html", context)


# --------------------------------------------------------------------------------------------- assistente


def _posted_filters(request) -> dict:
    """Filtros enviados no POST (JSON), já saneados, para reexibir o assistente após um erro."""
    try:
        raw = json.loads(request.POST.get("filters") or "{}")
    except ValueError:
        return {}
    if not isinstance(raw, dict):
        return {}
    return sanitize_voter_filters({k: v for k, v in raw.items() if k != "messageable"})


def _wizard_payload(request, form: BroadcastForm | None):
    """Estado inicial, modelos e conexões do assistente (tudo da campanha do usuário)."""
    user = request.user
    templates = list(template_scope(user).order_by("name"))
    connections = list(connected_connections(user))

    template_rows = [
        {
            "id": str(t.pk),
            "name": t.name,
            "category": t.get_category_display(),
            "type": t.type,
            "typeLabel": MEDIA_LABELS.get(t.type, "Texto"),
            "body": t.body,
            "mediaUrl": t.media_url,
            "providerTemplateName": t.provider_template_name,
        }
        for t in templates
    ]
    connection_rows = []
    for c in connections:
        definition = registry.get_provider_definition(c.provider)
        connection_rows.append(
            {
                "id": str(c.pk),
                "name": c.name,
                "provider": c.provider,
                "providerLabel": definition.label if definition else c.provider,
                "rate": c.rate_per_minute,
                "isDefault": c.is_default,
                "phone": c.phone_number,
                "requiresTemplate": bool(definition and definition.requires_approved_template),
            }
        )

    errors: dict[str, str] = {}
    if form is not None and form.is_bound:
        errors = {key: errs[0] for key, errs in form.errors.items() if errs}
        data = request.POST
        state = {
            "name": data.get("name", ""),
            "template": data.get("template", ""),
            "connection": data.get("connection", ""),
            "rate": data.get("rate_per_minute", ""),
            "mode": data.get("mode") if data.get("mode") in ("now", "schedule") else "now",
            "scheduledAt": data.get("scheduled_at", ""),
            "consent": bool(data.get("consent")),
            "filters": _posted_filters(request),
        }
    else:
        preselected = request.GET.get("modelo") or ""
        template_id = preselected if any(r["id"] == preselected for r in template_rows) else ""
        default_connection = connection_rows[0] if connection_rows else None
        state = {
            "name": "",
            "template": template_id,
            "connection": default_connection["id"] if default_connection else "",
            "rate": min(DEFAULT_RATE_PER_MINUTE, default_connection["rate"]) if default_connection else DEFAULT_RATE_PER_MINUTE,
            "mode": "now",
            "scheduledAt": "",
            "consent": False,
            "filters": {},
        }
    step = min((STEP_OF_FIELD.get(key, 3) for key in errors), default=0)
    config = {
        "templates": template_rows,
        "connections": connection_rows,
        "state": state,
        "errors": errors,
        "step": step,
        "example": EXAMPLE_CONTEXT,
        "urls": {
            "audience": "/api/painel/disparos/publico/",
            "templates": "/painel/mensagens/modelos/",
            "whatsapp": "/painel/whatsapp/",
        },
        "canViewTemplates": can(request.perms, "modelos", "view"),
        "defaultRate": DEFAULT_RATE_PER_MINUTE,
        "variables": TEMPLATE_VARIABLES,
        "mediaLabels": {k: v for k, v in MEDIA_LABELS.items()},
    }
    return config, state["filters"]


@module_permission_required("disparos", "create")
def broadcast_new(request):
    user = request.user
    form = None
    if request.method == "POST":
        throttle = rate_limit(f"broadcast-create:{user.pk}", 20, 10 * 60)
        if not throttle.ok:
            messages.error(request, "Muitos disparos criados em pouco tempo. Aguarde alguns minutos e tente de novo.")
            return redirect(BASE_URL)
        form = BroadcastForm(request.POST, user=user)
        if form.is_valid():
            return _create_broadcast(request, form)
        messages.error(request, "Revise os dados do disparo e tente de novo.")

    config, filters = _wizard_payload(request, form)
    return render(
        request,
        "messaging/broadcast_wizard.html",
        {
            "wizard_config": config,
            "filters": filters,
            "filter_options": get_voter_filter_options(user),
            "filter_hide": ["messageable"],
            "has_templates": bool(config["templates"]),
            "has_connections": bool(config["connections"]),
            "can_create_template": can(request.perms, "modelos", "create"),
            "can_view_whatsapp": can(request.perms, "whatsapp", "view"),
            "list_url": BASE_URL,
        },
    )


def _create_broadcast(request, form: BroadcastForm):
    user = request.user
    data = form.cleaned_data
    with transaction.atomic():
        # Trava o modelo: ele não pode ser excluído entre a validação e a criação do disparo
        template = MessageTemplate.objects.select_for_update().filter(pk=form.template_obj.pk, campaign_id=user.campaign_id).first()
        if template is None:
            messages.error(request, "O modelo escolhido não existe mais. Escolha outro e tente de novo.")
            return redirect(f"{BASE_URL}novo/")
        # Duplo clique / reenvio do formulário: o mesmo disparo não é criado duas vezes
        duplicate = Broadcast.objects.filter(
            campaign_id=user.campaign_id,
            created_by=user,
            template=template,
            name=data["name"].strip(),
            created_at__gte=timezone.now() - timedelta(seconds=DUPLICATE_WINDOW_SECONDS),
        ).first()
        if duplicate is not None:
            messages.info(request, "Este disparo já foi criado agora há pouco.")
            return redirect(_detail_url(duplicate))
        broadcast = Broadcast.objects.create(
            campaign_id=user.campaign_id,
            name=data["name"].strip(),
            template=template,
            connection=form.connection_obj,
            created_by=user,
            status=BroadcastStatus.SCHEDULED,
            filters=form.parsed_filters,
            scheduled_at=form.scheduled_for,
            rate_per_minute=data["rate_per_minute"],
        )
    audit(
        "broadcast.create",
        request=request,
        entity="Broadcast",
        entity_id=broadcast.pk,
        details={
            "template_id": str(template.pk),
            "connection_id": str(form.connection_obj.pk),
            "mode": data["mode"],
            "scheduled_at": broadcast.scheduled_at.isoformat() if broadcast.scheduled_at else None,
            "rate_per_minute": broadcast.rate_per_minute,
            "filter_keys": sorted(form.parsed_filters),
            "estimated_recipients": form.eligible,
            "consent_confirmed": True,
        },
    )

    if data["mode"] == "schedule":
        when = timezone.localtime(broadcast.scheduled_at).strftime("%d/%m/%Y às %H:%M")
        messages.success(request, f"Disparo agendado para {when}.")
        return redirect(_detail_url(broadcast))

    # Envio imediato: gera as mensagens agora. Se algo falhar, o disparo continua AGENDADO para já e o worker assume.
    try:
        result = materialize_broadcast(broadcast.pk)
    except Exception as exc:  # noqa: BLE001
        logger.error("Falha ao iniciar o disparo %s (%s)", broadcast.pk, type(exc).__name__)
        messages.warning(request, "O disparo foi criado e será iniciado em instantes.")
        return redirect(_detail_url(broadcast))

    if result.status == "FAILED":
        messages.error(request, result.reason or "Não foi possível iniciar o disparo.")
    elif result.started:
        audit(
            "broadcast.start",
            request=request,
            entity="Broadcast",
            entity_id=broadcast.pk,
            details={"recipients": result.recipients},
        )
        if result.recipients:
            messages.success(request, f"Disparo iniciado para {result.recipients} eleitor{'es' if result.recipients != 1 else ''}.")
        else:
            messages.warning(request, "Nenhum eleitor apto a receber mensagens foi encontrado. O disparo foi encerrado.")
    else:
        messages.success(request, "Disparo iniciado.")
    return redirect(_detail_url(broadcast))


# --------------------------------------------------------------------------------------------- detalhe


def _recipient_rows(request, page_items):
    """Nome e telefone dos destinatários. Quem não é ADMIN só vê dados de eleitores que ainda estão na sua rede."""
    user = request.user
    allowed = None
    if user.role != Role.ADMIN:
        ids = [m.voter_id for m in page_items if m.voter_id]
        allowed = set(voter_scope(user).filter(pk__in=ids).values_list("pk", flat=True)) if ids else set()
    for message in page_items:
        voter = message.voter
        if voter is None:
            message.display_name, message.display_phone = "Eleitor excluído", mask_phone(message.phone)
        elif allowed is not None and voter.pk not in allowed:
            message.display_name, message.display_phone = "Fora da sua rede", mask_phone(message.phone)
        else:
            message.display_name, message.display_phone = voter.name, format_phone(message.phone)
    return page_items


@module_permission_required("disparos", "view")
@never_cache
@vary_on_headers("HX-Request")
def broadcast_detail(request, pk):
    broadcast = _broadcast_or_404(request, pk)
    counters = load_status_counts(broadcast.pk)
    status_filter = request.GET.get("status") or ""

    recipients = (
        BroadcastMessage.objects.filter(broadcast_id=broadcast.pk, campaign_id=broadcast.campaign_id)
        .select_related("voter")
        .order_by("created_at", "id")
    )
    if status_filter in MessageStatus.values:
        recipients = recipients.filter(status=status_filter)
    else:
        status_filter = ""
    page = Paginator(recipients, RECIPIENTS_PER_PAGE).get_page(request.GET.get("page"))
    rows = _recipient_rows(request, list(page.object_list))

    can_edit = can(request.perms, "disparos", "edit")
    can_delete = can(request.perms, "disparos", "delete")
    retryable = BroadcastMessage.objects.filter(
        broadcast_id=broadcast.pk, status=MessageStatus.FAILED, attempts__lt=MAX_MANUAL_ATTEMPTS
    ).count()
    total = counters.total or broadcast.total_recipients
    delivery_rate, read_rate = broadcast_rates(counters.sent, counters.delivered, counters.read)
    template = broadcast.template
    is_live = broadcast.status in (BroadcastStatus.SCHEDULED, BroadcastStatus.RUNNING)
    # Entregas e leituras chegam por webhook DEPOIS de concluir o envio: a tela continua atualizando, mais devagar
    awaiting_receipts = (
        broadcast.status == BroadcastStatus.COMPLETED
        and broadcast.finished_at is not None
        and timezone.now() - broadcast.finished_at < RECEIPTS_POLL_WINDOW
    )
    poll_every = "5s" if is_live else ("15s" if awaiting_receipts else "")
    estimated_minutes = 0
    if broadcast.status in (BroadcastStatus.RUNNING, BroadcastStatus.PAUSED) and counters.queued:
        rate = min(broadcast.rate_per_minute, broadcast.connection.rate_per_minute) if broadcast.connection else broadcast.rate_per_minute
        estimated_minutes = -(-counters.queued // max(1, rate))

    context = {
        "broadcast": broadcast,
        "status_tone": BROADCAST_TONES.get(broadcast.status, "gray"),
        "stats": counters,
        "total": total,
        "progress_pct": percent(counters.processed, total),
        "delivery_rate": delivery_rate,
        "read_rate": read_rate,
        "delivery_hint": f"{delivery_rate:.0f}% das enviadas" if counters.sent else "",
        "read_hint": f"{read_rate:.0f}% das entregues" if counters.delivered else "",
        "empty_hint": (
            "As mensagens são preparadas quando chegar o horário agendado."
            if broadcast.status == BroadcastStatus.SCHEDULED
            else "Nenhum eleitor apto a receber mensagens foi encontrado para este público."
        ),
        "actions": available_actions(broadcast.status, retryable_failures=retryable, can_edit=can_edit, can_delete=can_delete),
        "retryable": retryable,
        "can_process": request.user.role == Role.ADMIN and is_live,
        "is_live": is_live,
        "awaiting_receipts": awaiting_receipts,
        "poll_every": poll_every,
        "remaining_label": format_duration(estimated_minutes) if estimated_minutes else "",
        "template_obj": template,
        "preview_text": render_template(template.body, EXAMPLE_CONTEXT) if template else "",
        "preview_media": MEDIA_LABELS.get(template.type, "") if template else "",
        "audience": describe_filters(broadcast.filters, broadcast.campaign_id),
        "page_obj": page,
        "recipients": rows,
        "status_filter": status_filter,
        "message_status_options": MessageStatus.choices,
        "refresh_url": request.get_full_path(),
        "scheduled_local": to_local_input(broadcast.scheduled_at) if broadcast.scheduled_at else "",
        "list_url": BASE_URL,
    }
    if request.headers.get("HX-Request"):
        return render(request, "messaging/_broadcast_detail_live.html", context)
    return render(request, "messaging/broadcast_detail.html", context)


# --------------------------------------------------------------------------------------------- ações (POST)


@module_permission_required("disparos", "edit")
@require_POST
def broadcast_control(request, pk, control):
    """Pausar, retomar, cancelar ou reenviar falhas. A máquina de estados está em logic.py."""
    if control not in CONTROLS:
        raise Http404("Ação inexistente.")
    broadcast = _broadcast_or_404(request, pk)
    url = _detail_url(broadcast)
    now = timezone.now()

    if next_broadcast_status(broadcast.status, control) is None:
        messages.error(
            request,
            f"Esta ação não está disponível para disparos com status “{label_of(BroadcastStatus, broadcast.status)}”.",
        )
        return redirect(url)

    if control in ("resume", "retry"):
        problem = broadcast_send_problem(broadcast)
        if problem:
            messages.error(request, problem)
            return redirect(url)

    changed = 0
    if control == "pause":
        changed = Broadcast.objects.filter(pk=broadcast.pk, status__in=allowed_from("pause")).update(
            status=BroadcastStatus.PAUSED, updated_at=now
        )
        done = "Disparo pausado. Nenhuma nova mensagem será enviada até você retomar."
    elif control == "resume":
        changed = Broadcast.objects.filter(pk=broadcast.pk, status__in=allowed_from("resume")).update(
            status=BroadcastStatus.RUNNING, updated_at=now
        )
        done = "Disparo retomado."
    elif control == "cancel":
        with transaction.atomic():
            changed = Broadcast.objects.filter(pk=broadcast.pk, status__in=allowed_from("cancel")).update(
                status=BroadcastStatus.CANCELLED, finished_at=now, updated_at=now
            )
            if changed:
                BroadcastMessage.objects.filter(broadcast_id=broadcast.pk, status=MessageStatus.PENDING).update(
                    status=MessageStatus.SKIPPED, error="Cancelado", updated_at=now
                )
        done = "Disparo cancelado. As mensagens que ainda estavam na fila não serão enviadas."
    else:  # retry
        requeued = 0
        with transaction.atomic():
            changed = Broadcast.objects.filter(pk=broadcast.pk, status__in=allowed_from("retry")).update(
                status=BroadcastStatus.RUNNING, finished_at=None, updated_at=now
            )
            if changed:
                requeued = BroadcastMessage.objects.filter(
                    broadcast_id=broadcast.pk, status=MessageStatus.FAILED, attempts__lt=MAX_MANUAL_ATTEMPTS
                ).update(status=MessageStatus.PENDING, error="", updated_at=now)
                if not requeued:
                    transaction.set_rollback(True)  # nada para reenviar: mantém o status atual
        if changed and not requeued:
            messages.info(request, "Não há mensagens com falha que possam ser reenviadas.")
            return redirect(url)
        done = (
            "1 mensagem com falha voltou para a fila."
            if requeued == 1
            else f"{requeued} mensagens com falha voltaram para a fila."
        )

    if not changed:
        messages.error(request, "O status do disparo mudou enquanto você usava a página. Confira o estado atual.")
        return redirect(url)

    refresh_broadcast_counters(broadcast.pk)
    audit(
        f"broadcast.{control}",
        request=request,
        entity="Broadcast",
        entity_id=broadcast.pk,
        details={"from": broadcast.status},
    )
    messages.success(request, done)
    return redirect(url)


@module_permission_required("disparos", "delete")
@require_POST
def broadcast_delete(request, pk):
    broadcast = _broadcast_or_404(request, pk)
    if not can_delete_broadcast(broadcast.status):
        messages.error(request, "Pause ou cancele o disparo antes de excluí-lo.")
        return redirect(_detail_url(broadcast))
    with transaction.atomic():
        removed, _ = Broadcast.objects.filter(pk=broadcast.pk).exclude(status=BroadcastStatus.RUNNING).delete()
    if not removed:
        messages.error(request, "O disparo voltou a ser executado. Pause ou cancele antes de excluí-lo.")
        return redirect(_detail_url(broadcast))
    audit(
        "broadcast.delete",
        request=request,
        entity="Broadcast",
        entity_id=broadcast.pk,
        details={"status": broadcast.status, "recipients": broadcast.total_recipients},
    )
    messages.success(request, "Disparo excluído.")
    return redirect(BASE_URL)


@admin_required
@require_POST
def broadcast_process_now(request, pk):
    """Roda um ciclo da fila da campanha (útil no desenvolvimento, sem o worker)."""
    broadcast = _broadcast_or_404(request, pk)
    throttle = rate_limit(f"queue-now:{request.user.pk}", 12, 60)
    if not throttle.ok:
        messages.error(request, "Aguarde alguns segundos antes de processar a fila de novo.")
        return redirect(_detail_url(broadcast))
    report = run_queue_tick(campaign_id=request.user.campaign_id, max_messages=50)
    parts = []
    if report["materialized"]:
        parts.append(f"{report['materialized']} disparo(s) iniciado(s)")
    parts.append(f"{report['sent']} enviada(s)")
    if report["failed"]:
        parts.append(f"{report['failed']} com falha")
    if report["skipped"]:
        parts.append(f"{report['skipped']} ignorada(s)")
    messages.success(request, "Fila processada: " + ", ".join(parts) + ".")
    return redirect(_detail_url(broadcast))
