"""Painel de apoiadores: lista, exportação, cadastro manual, detalhe, edição, descadastro, troca de responsável e
exclusão. Todas as consultas passam pelo escopo hierárquico (`apps.core.access`)."""

from __future__ import annotations

from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from apps.auditlog.service import audit
from apps.core.access import MESSAGEABLE_Q, get_voter_in_scope, voter_scope, voters_queryset
from apps.core.constants import GeoStatus, MessageStatus, Role, VoterSource, label_of
from apps.core.decorators import admin_required, module_permission_required
from apps.core.filter_options import get_voter_filter_options
from apps.core.http import csv_response
from apps.core.phone import normalize_br_phone
from apps.core.utils import age_from, client_ip, to_csv
from apps.core.voter_filters import parse_voter_filters, voter_filters_to_params
from apps.geo.geocode import geocode_voter_in_background
from apps.messaging.models import BroadcastMessage
from apps.whatsapp.models import InboundMessage

from .display import decorate_voter, decorate_voters, message_status_tone
from .export import EXPORT_COLUMNS, MAX_EXPORT_ROWS, audit_safe_filters, export_filename, voter_to_export_row
from .forms import (
    ChangeRegistrarForm,
    VoterCreateForm,
    VoterEditForm,
    voter_data_from_cleaned,
    voter_initial,
)
from .merge import geo_address_changed
from .models import Voter
from .utils import VOTER_SORTS, parse_voter_sort, safe_ip, sort_expressions

PAGE_SIZE = 25


def _has_address(data: dict) -> bool:
    return any(data.get(k) for k in ("cep", "street", "neighborhood", "city"))


# ---------------------------------------------------------------------------------------------
# Lista e exportação
# ---------------------------------------------------------------------------------------------


@module_permission_required("eleitores", "view")
@never_cache
@require_GET
def voter_list(request):
    user = request.user
    filters = parse_voter_filters(request.GET)
    sort = parse_voter_sort(request.GET.get("ordem"))
    qs = voters_queryset(user, filters)
    total = qs.count()
    messageable = qs.filter(MESSAGEABLE_Q).count()
    page_obj = Paginator(qs.select_related("registered_by").order_by(*sort_expressions(sort)), PAGE_SIZE).get_page(
        request.GET.get("page")
    )
    decorate_voters(page_obj.object_list)

    export_params = voter_filters_to_params(filters) + ([("ordem", sort)] if sort != "recentes" else [])
    failed_geo = 0
    if user.role == Role.ADMIN:
        failed_geo = _retryable_geo_failures(request.campaign.pk).count()

    return render(
        request,
        "voters/list.html",
        {
            "filters": filters,
            "filter_options": get_voter_filter_options(user),
            "page_obj": page_obj,
            "voters": page_obj.object_list,
            "total": total,
            "messageable": messageable,
            "sort": sort,
            "sort_options": list(VOTER_SORTS.items()),
            "export_query": urlencode(export_params),
            "failed_geo": failed_geo,
            "has_filters": bool(filters),
        },
    )


@module_permission_required("eleitores", "export")
@never_cache
@require_GET
def voter_export(request):
    filters = parse_voter_filters(request.GET)
    sort = parse_voter_sort(request.GET.get("ordem"))
    qs = voters_queryset(request.user, filters).select_related("registered_by").order_by(*sort_expressions(sort))
    rows = [voter_to_export_row(v) for v in qs[:MAX_EXPORT_ROWS].iterator(chunk_size=2000)]
    audit(
        "voter.export",
        request=request,
        entity="Voter",
        details={"count": len(rows), "filters": audit_safe_filters(filters)},
    )
    return csv_response(to_csv(rows, EXPORT_COLUMNS), export_filename())


def _retryable_geo_failures(campaign_id):
    """Apoiadores não localizados que têm endereço para tentar de novo (CEP ou cidade)."""
    return Voter.objects.filter(campaign_id=campaign_id, geo_status=GeoStatus.FAILED).filter(~Q(cep="") | ~Q(city=""))


@admin_required
@require_POST
def retry_geo(request):
    count = _retryable_geo_failures(request.campaign.pk).update(
        geo_status=GeoStatus.PENDING, latitude=None, longitude=None
    )
    audit("voter.update", request=request, entity="Voter", details={"change": "geo_retry", "count": count})
    if count:
        messages.success(request, f"{count} apoiador(es) entraram na fila para serem localizados novamente.")
    else:
        messages.info(request, "Não há apoiadores para localizar novamente.")
    return redirect("voters:list")


# ---------------------------------------------------------------------------------------------
# Cadastro manual
# ---------------------------------------------------------------------------------------------


def _existing_in_scope(user, form):
    """Se o erro é de telefone duplicado e o outro cadastro está no escopo do usuário, devolve-o (para o link)."""
    errors = form.errors.as_data().get("phone")
    if not errors or errors[0].code != "duplicate":
        return None
    phone = normalize_br_phone(form.data.get("phone"))
    return voter_scope(user).filter(phone=phone).first() if phone else None


@module_permission_required("eleitores", "create")
@never_cache
def voter_create(request):
    user = request.user
    form = VoterCreateForm(request.POST if request.method == "POST" else None, user=user)
    if request.method == "POST" and form.is_valid():
        cleaned = form.cleaned_data
        registrar = cleaned.get("registered_by") or user
        data = voter_data_from_cleaned(cleaned)
        try:
            with transaction.atomic():
                voter = Voter.objects.create(
                    campaign_id=user.campaign_id,
                    registered_by=registrar,
                    support_level=cleaned.get("support_level") or "",
                    tags=cleaned.get("tags") or "",
                    notes=cleaned.get("notes") or "",
                    source=VoterSource.MANUAL,
                    consent_at=timezone.now(),
                    consent_ip=safe_ip(client_ip(request)),
                    consent_text=f"Consentimento (LGPD) declarado no cadastro manual por {user.name}.",
                    whatsapp_opt_in=bool(cleaned.get("whatsapp_opt_in")),
                    geo_status=GeoStatus.PENDING,
                    **data,
                )
        except IntegrityError:
            form.add_error("phone", "Telefone já cadastrado na campanha.")
        else:
            audit(
                "voter.create",
                request=request,
                entity="Voter",
                entity_id=voter.pk,
                details={"voter_id": str(voter.pk), "source": VoterSource.MANUAL.value},
            )
            if _has_address(data):
                geocode_voter_in_background(voter.pk)
            messages.success(request, "Apoiador cadastrado com sucesso.")
            return redirect("voters:detail", voter_id=voter.pk)

    return render(
        request,
        "voters/form.html",
        {
            "form": form,
            "mode": "create",
            "duplicate": _existing_in_scope(user, form) if form.is_bound else None,
        },
    )


# ---------------------------------------------------------------------------------------------
# Detalhe, edição e ações
# ---------------------------------------------------------------------------------------------


def _voter_or_404(request, voter_id):
    voter = get_voter_in_scope(request.user, voter_id)
    if voter is None:
        raise Http404("Apoiador não encontrado.")
    return voter


@module_permission_required("eleitores", "view")
@never_cache
@require_GET
def voter_detail(request, voter_id):
    from apps.messaging.models import BroadcastMessage

    voter = _voter_or_404(request, voter_id)
    audit("voter.view", request=request, entity="Voter", entity_id=voter.pk)  # só o id, sem dados pessoais
    decorate_voter(voter)
    history = list(
        BroadcastMessage.objects.filter(voter_id=voter.pk, campaign_id=voter.campaign_id)
        .select_related("broadcast")
        .order_by("-created_at")[:20]
    )
    for item in history:
        item.status_label = label_of(MessageStatus, item.status)
        item.status_tone = message_status_tone(item.status)
    registrar_form = (
        ChangeRegistrarForm(initial={"registered_by": voter.registered_by_id}, campaign_id=voter.campaign_id)
        if request.user.role == Role.ADMIN
        else None
    )
    return render(
        request,
        "voters/detail.html",
        {
            "voter": voter,
            "registrar": voter.registered_by,
            "subtitle": f"Cadastrado por {voter.registered_by.name} em {timezone.localtime(voter.created_at):%d/%m/%Y}",
            "age": age_from(voter.birth_date, timezone.localdate()) if voter.birth_date else None,
            "history": history,
            "registrar_form": registrar_form,
        },
    )


@module_permission_required("eleitores", "edit")
@never_cache
def voter_edit(request, voter_id):
    voter = _voter_or_404(request, voter_id)
    if request.method == "POST":
        form = VoterEditForm(request.POST, voter=voter)
        if form.is_valid():
            cleaned = form.cleaned_data
            data = voter_data_from_cleaned(cleaned)
            extra = {
                "support_level": cleaned.get("support_level") or "",
                "tags": cleaned.get("tags") or "",
                "notes": cleaned.get("notes") or "",
            }
            changed = [k for k, v in {**data, **extra}.items() if getattr(voter, k) != v]
            address_changed = geo_address_changed(voter, data)
            try:
                with transaction.atomic():
                    for key, value in {**data, **extra}.items():
                        setattr(voter, key, value)
                    if address_changed:
                        voter.geo_status = GeoStatus.PENDING
                        voter.latitude = None
                        voter.longitude = None
                    voter.save()
            except IntegrityError:
                form.add_error("phone", "Telefone já cadastrado na campanha.")
            else:
                if changed:
                    audit(
                        "voter.update",
                        request=request,
                        entity="Voter",
                        entity_id=voter.pk,
                        details={"voter_id": str(voter.pk), "fields": changed},
                    )
                if address_changed and _has_address(data):
                    geocode_voter_in_background(voter.pk)
                messages.success(request, "Dados do apoiador atualizados.")
                return redirect("voters:detail", voter_id=voter.pk)
    else:
        form = VoterEditForm(voter=voter, initial=voter_initial(voter))
    return render(
        request,
        "voters/form.html",
        {
            "form": form,
            "mode": "edit",
            "voter": voter,
            "duplicate": _existing_in_scope(request.user, form) if form.is_bound else None,
        },
    )


@module_permission_required("eleitores", "edit")
@require_POST
def voter_opt_out(request, voter_id):
    voter = _voter_or_404(request, voter_id)
    if voter.opt_out_at is None:
        voter.opt_out_at = timezone.now()
        voter.save(update_fields=["opt_out_at", "updated_at"])
        audit("voter.opt_out", request=request, entity="Voter", entity_id=voter.pk, details={"voter_id": str(voter.pk)})
        messages.success(request, "Apoiador descadastrado dos disparos de WhatsApp.")
    else:
        messages.info(request, "Este apoiador já está descadastrado do WhatsApp.")
    return redirect("voters:detail", voter_id=voter.pk)


@admin_required
@require_POST
def voter_change_registrar(request, voter_id):
    voter = _voter_or_404(request, voter_id)
    form = ChangeRegistrarForm(request.POST, campaign_id=voter.campaign_id)
    if not form.is_valid():
        messages.error(request, "Selecione um membro da equipe desta campanha.")
        return redirect("voters:detail", voter_id=voter.pk)
    new_owner = form.cleaned_data["registered_by"]
    if new_owner.pk == voter.registered_by_id:
        messages.info(request, "O apoiador já está vinculado a este membro da equipe.")
        return redirect("voters:detail", voter_id=voter.pk)
    previous = voter.registered_by_id
    voter.registered_by = new_owner
    voter.save(update_fields=["registered_by", "updated_at"])
    audit(
        "voter.update",
        request=request,
        entity="Voter",
        entity_id=voter.pk,
        details={
            "voter_id": str(voter.pk),
            "change": "registered_by",
            "from": str(previous),
            "to": str(new_owner.pk),
        },
    )
    messages.success(request, f"Apoiador transferido para {new_owner.name}.")
    return redirect("voters:detail", voter_id=voter.pk)


@module_permission_required("eleitores", "delete")
@require_POST
def voter_delete(request, voter_id):
    voter = _voter_or_404(request, voter_id)
    voter_pk = str(voter.pk)
    with transaction.atomic():
        # Direito de eliminação (LGPD, art. 18, VI): as linhas de histórico mantêm só status/contagens,
        # sem o telefone, o texto enviado ou a mensagem recebida do titular.
        BroadcastMessage.objects.filter(voter=voter).update(phone="", rendered_body="", error="")
        InboundMessage.objects.filter(voter=voter).update(from_phone="", body="")
        voter.delete()  # exclusão definitiva
    audit("voter.delete", request=request, entity="Voter", entity_id=voter_pk, details={"voter_id": voter_pk})
    messages.success(request, "Apoiador excluído definitivamente.")
    return redirect("voters:list")

