"""Site público (landing, privacidade, termos) e, no painel, configurações e auditoria da campanha."""

from __future__ import annotations

from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_safe

from apps.auditlog.service import audit
from apps.core.constants import (
    DEFAULT_CONSENT_TEXT,
    DEFAULT_WHATSAPP_OPTIN_TEXT,
    CampaignStatus,
    Role,
    label_of,
)
from apps.core.decorators import module_permission_required
from apps.core.http import csv_response
from apps.core.permissions import can
from apps.core.qr import registration_url
from apps.core.utils import to_csv

from .audit_rules import AUDIT_EXPORT_LIMIT, AUDIT_PAGE_SIZE, export_filename
from .forms import IdentityForm, PublicFormSettingsForm
from .services import (
    AUDIT_CSV_COLUMNS,
    IDENTITY_FIELDS,
    PUBLIC_FORM_FIELDS,
    apply_audit_filters,
    audit_csv_rows,
    audit_filter_options,
    audit_queryset,
    audit_row,
    read_audit_filters,
    save_campaign_settings,
    with_users,
)
from .settings_rules import (
    DEFAULT_PRIMARY_COLOR,
    LIMITS,
    LOGO_ACCEPTED_MIMES,
    LOGO_MAX_BYTES,
    LOGO_MAX_DIMENSION,
    LOGO_MAX_SOURCE_BYTES,
    is_safe_logo_url,
    normalize_hex_color,
    readable_text_color,
)

CONTACT_EMAIL = "contato@efind.com.br"
LEGAL_LAST_UPDATED = "outubro de 2026"


# --- Site público -------------------------------------------------------------------------------------
@require_safe
def landing(request):
    """Página inicial de efind.com.br (pública; o CTA muda quando há sessão ativa)."""
    user = request.user
    if user.is_authenticated:
        cta_href = "/super/" if user.role == Role.SUPER_ADMIN else "/painel/"
        cta_label = "Ir para o painel"
    else:
        cta_href, cta_label = "/login/", "Acessar painel"
    return render(
        request,
        "portal/landing.html",
        {"cta_href": cta_href, "cta_label": cta_label, "contact_email": CONTACT_EMAIL},
    )


@require_safe
def privacy(request):
    return render(
        request,
        "portal/privacy.html",
        {"last_updated": LEGAL_LAST_UPDATED, "contact_email": CONTACT_EMAIL},
    )


@require_safe
def terms(request):
    return render(
        request,
        "portal/terms.html",
        {"last_updated": LEGAL_LAST_UPDATED, "contact_email": CONTACT_EMAIL},
    )


# --- Configurações da campanha ------------------------------------------------------------------------
def _settings_js_config() -> dict:
    return {
        "defaultConsent": DEFAULT_CONSENT_TEXT,
        "optInText": DEFAULT_WHATSAPP_OPTIN_TEXT,
        "defaultColor": DEFAULT_PRIMARY_COLOR,
        "limits": {"consentMax": LIMITS["consent_text_max"], "messageMax": LIMITS["form_message"]},
        "logo": {
            "maxBytes": LOGO_MAX_BYTES,
            "maxDimension": LOGO_MAX_DIMENSION,
            "maxSourceBytes": LOGO_MAX_SOURCE_BYTES,
            "accepted": list(LOGO_ACCEPTED_MIMES),
        },
    }


@module_permission_required("configuracoes")
@never_cache
def settings_view(request):
    """Identidade da campanha e formulário público de cadastro. Salvar exige `configuracoes.edit`.

    A campanha é sempre a do usuário logado; nenhum id de campanha vem do cliente. Cada cartão é um formulário
    próprio (campo oculto `section`) e só os campos que mudaram são gravados e auditados.
    """
    campaign = request.campaign
    can_edit = can(request.perms, "configuracoes", "edit")
    identity_form = IdentityForm(initial=IdentityForm.initial_from(campaign))
    public_form = PublicFormSettingsForm(initial=PublicFormSettingsForm.initial_from(campaign))

    if request.method == "POST":
        if not can_edit:
            raise PermissionDenied("Você não tem permissão para editar as configurações da campanha.")
        section = request.POST.get("section")
        if section == "identity":
            identity_form = IdentityForm(request.POST)
            if identity_form.is_valid():
                changed = save_campaign_settings(
                    request,
                    campaign,
                    identity_form.campaign_values(campaign),
                    section="identidade",
                    fields=IDENTITY_FIELDS,
                )
                if changed:
                    messages.success(request, "Identidade da campanha salva.")
                else:
                    messages.info(request, "Nenhuma alteração para salvar.")
                return redirect(f"{request.path}#identidade")
            messages.error(request, "Verifique os campos destacados na identidade da campanha.")
        elif section == "public_form":
            public_form = PublicFormSettingsForm(request.POST)
            if public_form.is_valid():
                changed = save_campaign_settings(
                    request,
                    campaign,
                    public_form.campaign_values(),
                    section="formulario_publico",
                    fields=PUBLIC_FORM_FIELDS,
                )
                if changed:
                    messages.success(request, "Formulário público salvo.")
                else:
                    messages.info(request, "Nenhuma alteração para salvar.")
                return redirect(f"{request.path}#formulario")
            messages.error(request, "Verifique os campos destacados no formulário público.")
        else:
            messages.error(request, "Requisição inválida.")
            return redirect(request.path)

    # Estado do logo ao (re)renderizar: se o envio falhou por outro campo, preserva o logo novo já validado
    logo_action, logo_echo = "keep", ""
    if identity_form.is_bound:
        posted = identity_form.data.get("logo_action")
        cleaned = getattr(identity_form, "cleaned_data", {})
        if posted == "replace" and "logo_data" not in identity_form.errors and cleaned.get("logo_data"):
            logo_action, logo_echo = "replace", cleaned["logo_data"]
        elif posted == "remove":
            logo_action = "remove"

    saved_logo = campaign.logo_url if is_safe_logo_url(campaign.logo_url) else ""
    color = normalize_hex_color(identity_form["primary_color"].value()) or DEFAULT_PRIMARY_COLOR
    context = {
        "campaign": campaign,
        "can_edit": can_edit,
        "identity_form": identity_form,
        "public_form": public_form,
        "mode_rows": public_form.mode_rows(),
        "logo_action": logo_action,
        "logo_echo": logo_echo,
        "color_value": color,
        "color_text": readable_text_color(color),
        "registration_path": f"/c/{request.user.invite_code}/",
        "registration_link": registration_url(request.user.invite_code),
        "saved_logo": saved_logo,
        "logo_state": {"saved": saved_logo, "action": logo_action, "echo": logo_echo},
        "campaign_active": campaign.status == CampaignStatus.ACTIVE,
        "campaign_status_label": label_of(CampaignStatus, campaign.status),
        "js_config": _settings_js_config(),
        "limits": LIMITS,
    }
    return render(request, "portal/settings.html", context)


# --- Auditoria ----------------------------------------------------------------------------------------
@module_permission_required("auditoria")
@never_cache
def audit_log(request):
    """Trilha de auditoria SOMENTE da campanha do usuário (ADMIN: toda; demais: a própria rede)."""
    campaign = request.campaign
    options = audit_filter_options(campaign, request.user)
    filters = read_audit_filters(request.GET, options)
    queryset = apply_audit_filters(audit_queryset(campaign, request.user), filters)
    paginator = Paginator(with_users(queryset), AUDIT_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    context = {
        "page_obj": page_obj,
        "rows": [audit_row(log) for log in page_obj.object_list],
        "total": paginator.count,
        "filters": filters,
        "options": options,
        "export_query": urlencode(filters.to_params()),
    }
    return render(request, "portal/audit.html", context)


@module_permission_required("auditoria")
@require_GET
@never_cache
def audit_export(request):
    """CSV da trilha filtrada (mesma permissão e mesmo escopo da listagem). A exportação também é auditada."""
    campaign = request.campaign
    options = audit_filter_options(campaign, request.user)
    filters = read_audit_filters(request.GET, options)
    queryset = apply_audit_filters(audit_queryset(campaign, request.user), filters)
    rows, truncated = audit_csv_rows(queryset)
    if truncated:
        limit = f"{AUDIT_EXPORT_LIMIT:,}".replace(",", ".")
        rows.append({"data_hora": f"Exportação limitada aos {limit} registros mais recentes. Use os filtros para refinar."})
    audit(
        "audit.export",
        request=request,
        campaign=campaign,
        entity="AuditLog",
        details={"count": min(len(rows), AUDIT_EXPORT_LIMIT), "filters": filters.audit_details(), "truncated": truncated},
    )
    return csv_response(to_csv(rows, AUDIT_CSV_COLUMNS), export_filename(filters, timezone.localdate()))
