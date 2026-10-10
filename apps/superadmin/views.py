"""Views do super admin (/super/...). Toda view começa com @super_admin_required e muta estado só via POST.

PRIVACIDADE: nenhuma view carrega eleitores — só contagens agregadas (veja selectors.py). O contexto da campanha
gerenciada vai nos templates como `camp` (o nome `campaign` é reservado ao context processor do painel).
"""

from __future__ import annotations

import copy

from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.cache import add_never_cache_headers
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.campaigns.models import Campaign
from apps.core.constants import Role
from apps.core.decorators import super_admin_required

from . import selectors
from .forms import (
    EMAIL_TAKEN,
    AccountForm,
    AuditFilterForm,
    CampaignForm,
    CampaignListForm,
    DeleteCampaignForm,
)
from .services import (
    EmailAlreadyUsed,
    ServiceError,
    create_account,
    create_campaign_with_admin,
    delete_campaign,
    reset_password,
    set_campaign_status,
    set_user_active,
    update_campaign,
)

CAMPAIGN_PAGE_SIZE = 25
AUDIT_PAGE_SIZE = 50
DETAIL_TABS = ("dados", "administradores", "uso")


def _detail_url(campaign: Campaign, tab: str = "dados") -> str:
    url = reverse("superadmin:campaign_detail", args=[campaign.pk])
    return f"{url}#{tab}" if tab in DETAIL_TABS and tab != "dados" else url


def _credentials_page(request, creds, *, title: str, description: str, back_url: str, back_label: str):
    """Mostra credenciais emitidas UMA vez, direto na resposta do POST (nada vai para sessão/banco/auditoria)."""
    response = render(
        request,
        "superadmin/credentials.html",
        {"creds": creds, "title": title, "description": description, "back_url": back_url, "back_label": back_label},
    )
    add_never_cache_headers(response)
    return response


# ---------------------------------------------------------------------------------------------
# Visão geral e lista de campanhas
# ---------------------------------------------------------------------------------------------


@super_admin_required
def home(request):
    return render(request, "superadmin/home.html", {"overview": selectors.platform_overview()})


@super_admin_required
def campaign_list(request):
    form = CampaignListForm(request.GET)
    form.is_valid()
    data = form.cleaned_data  # campos inválidos simplesmente ficam de fora
    queryset = selectors.search_campaigns(selectors.campaigns_with_counts(), data.get("q", ""), data.get("status", ""))
    page = Paginator(queryset, CAMPAIGN_PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "superadmin/campaign_list.html",
        {
            "form": form,
            "page_obj": page,
            "campaigns": selectors.decorate_campaigns(page.object_list),
            "filtered": bool(data.get("q") or data.get("status")),
        },
    )


# ---------------------------------------------------------------------------------------------
# Criação
# ---------------------------------------------------------------------------------------------


@super_admin_required
def campaign_create(request):
    if request.method == "POST":
        campaign_form = CampaignForm(request.POST)
        admin_form = AccountForm(request.POST, prefix="admin")
        # Valida os dois para mostrar todos os erros de uma vez
        if campaign_form.is_valid() & admin_form.is_valid():
            try:
                campaign, _admin, creds = create_campaign_with_admin(
                    request, campaign_data=campaign_form.cleaned_data, admin_data=admin_form.cleaned_data
                )
            except EmailAlreadyUsed:
                admin_form.add_error("email", EMAIL_TAKEN)
            except ServiceError as exc:
                messages.error(request, str(exc))
            else:
                response = render(
                    request,
                    "superadmin/campaign_created.html",
                    {"camp": selectors.decorate_campaign(campaign), "creds": creds},
                )
                add_never_cache_headers(response)
                return response
        else:
            messages.error(request, "Verifique os campos destacados.")
    else:
        campaign_form = CampaignForm()
        admin_form = AccountForm(prefix="admin")
    return render(
        request, "superadmin/campaign_form.html", {"form": campaign_form, "admin_form": admin_form}
    )


# ---------------------------------------------------------------------------------------------
# Detalhe da campanha
# ---------------------------------------------------------------------------------------------


def _render_detail(request, campaign: Campaign, *, tab: str = "dados", form=None, admin_form=None, delete_form=None):
    selectors.decorate_campaign(campaign)
    context = {
        "camp": campaign,
        "active_tab": tab,
        "form": form if form is not None else CampaignForm(instance=campaign),
        "admin_form": admin_form if admin_form is not None else AccountForm(auto_id="admin_%s"),
        "delete_form": delete_form if delete_form is not None else DeleteCampaignForm(campaign=campaign),
        "admins": selectors.campaign_admins(campaign),
        "usage": selectors.campaign_usage(campaign),
    }
    return render(request, "superadmin/campaign_detail.html", context)


@super_admin_required
def campaign_detail(request, pk):
    return _render_detail(request, get_object_or_404(Campaign, pk=pk))


@super_admin_required
@require_POST
def campaign_update(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    form = CampaignForm(request.POST, instance=copy.copy(campaign))  # o form altera a instância mesmo se inválido
    if not form.is_valid():
        messages.error(request, "Verifique os campos destacados.")
        return _render_detail(request, campaign, tab="dados", form=form)
    if update_campaign(request, form):
        messages.success(request, "Dados da campanha atualizados.")
    else:
        messages.info(request, "Nenhuma alteração para salvar.")
    return redirect(_detail_url(campaign))


def _change_status(request, pk, *, suspend: bool):
    campaign = get_object_or_404(Campaign, pk=pk)
    paused = set_campaign_status(request, campaign, suspend=suspend)
    if paused is None:
        messages.info(request, "A campanha já está suspensa." if suspend else "A campanha já está ativa.")
    elif suspend:
        extra = f" {paused} disparo(s) em andamento foram pausados." if paused else ""
        messages.success(request, f"Campanha suspensa. A equipe não consegue mais entrar.{extra}")
    else:
        messages.success(request, "Campanha reativada. A equipe já pode entrar novamente.")
    return redirect(_detail_url(campaign))


@super_admin_required
@require_POST
def campaign_suspend(request, pk):
    return _change_status(request, pk, suspend=True)


@super_admin_required
@require_POST
def campaign_activate(request, pk):
    return _change_status(request, pk, suspend=False)


@super_admin_required
@require_POST
def campaign_delete(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    form = DeleteCampaignForm(request.POST, campaign=campaign)
    if not form.is_valid():
        return _render_detail(request, campaign, tab="dados", delete_form=form)
    ballot_name = campaign.ballot_name
    try:
        delete_campaign(request, campaign)
    except ServiceError as exc:
        messages.error(request, str(exc))
        return redirect(_detail_url(campaign))
    messages.success(request, f"Campanha “{ballot_name}” excluída definitivamente.")
    return redirect("superadmin:campaigns")


# ---------------------------------------------------------------------------------------------
# Administradores da campanha
# ---------------------------------------------------------------------------------------------


def _campaign_admin_or_404(campaign: Campaign, user_id) -> User:
    """Administrador DESTA campanha (id de outra campanha ou de outro papel → 404)."""
    return get_object_or_404(User, pk=user_id, campaign=campaign, role=Role.ADMIN)


@super_admin_required
@require_POST
def campaign_admin_create(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    form = AccountForm(request.POST, auto_id="admin_%s")
    if form.is_valid():
        try:
            _user, creds = create_account(request, role=Role.ADMIN, campaign=campaign, data=form.cleaned_data)
        except EmailAlreadyUsed:
            form.add_error("email", EMAIL_TAKEN)
        except ServiceError as exc:
            messages.error(request, str(exc))
        else:
            return _credentials_page(
                request,
                creds,
                title="Administrador criado",
                description=f"Novo administrador da campanha {campaign.ballot_name}.",
                back_url=_detail_url(campaign, "administradores"),
                back_label="Voltar à campanha",
            )
    else:
        messages.error(request, "Verifique os campos destacados.")
    return _render_detail(request, campaign, tab="administradores", admin_form=form)


@super_admin_required
@require_POST
def campaign_admin_reset_password(request, pk, user_id):
    campaign = get_object_or_404(Campaign, pk=pk)
    admin = _campaign_admin_or_404(campaign, user_id)
    creds = reset_password(request, admin, campaign=campaign)
    return _credentials_page(
        request,
        creds,
        title="Senha redefinida",
        description="As sessões abertas deste usuário foram encerradas. A senha anterior não funciona mais.",
        back_url=_detail_url(campaign, "administradores"),
        back_label="Voltar à campanha",
    )


@super_admin_required
@require_POST
def campaign_admin_set_active(request, pk, user_id, active):
    campaign = get_object_or_404(Campaign, pk=pk)
    admin = _campaign_admin_or_404(campaign, user_id)
    try:
        changed = set_user_active(request, admin, active=active, campaign=campaign)
    except ServiceError as exc:
        messages.error(request, str(exc))
    else:
        if not changed:
            messages.info(request, "O administrador já está ativo." if active else "O administrador já está desativado.")
        elif active:
            messages.success(request, "Administrador reativado.")
        else:
            messages.success(request, "Administrador desativado. As sessões dele foram encerradas.")
    return redirect(_detail_url(campaign, "administradores"))


# ---------------------------------------------------------------------------------------------
# Super admins
# ---------------------------------------------------------------------------------------------


def _render_users(request, form=None, *, open_form: bool = False):
    return render(
        request,
        "superadmin/users.html",
        {
            "accounts": selectors.super_users(),
            "form": form if form is not None else AccountForm(),
            "open_form": open_form,
        },
    )


@super_admin_required
def users(request):
    return _render_users(request)


@super_admin_required
@require_POST
def user_create(request):
    form = AccountForm(request.POST)
    if form.is_valid():
        try:
            _user, creds = create_account(request, role=Role.SUPER_ADMIN, campaign=None, data=form.cleaned_data)
        except EmailAlreadyUsed:
            form.add_error("email", EMAIL_TAKEN)
        except ServiceError as exc:
            messages.error(request, str(exc))
        else:
            return _credentials_page(
                request,
                creds,
                title="Super admin criado",
                description="Nova conta com acesso à administração da plataforma.",
                back_url=reverse("superadmin:users"),
                back_label="Voltar aos super admins",
            )
    else:
        messages.error(request, "Verifique os campos destacados.")
    return _render_users(request, form, open_form=True)


def _super_user_or_404(user_id) -> User:
    return get_object_or_404(User, pk=user_id, role=Role.SUPER_ADMIN)


@super_admin_required
@require_POST
def user_reset_password(request, user_id):
    target = _super_user_or_404(user_id)
    if target.pk == request.user.pk:
        messages.error(request, "Para trocar a sua própria senha, use a página Meu perfil.")
        return redirect("superadmin:users")
    creds = reset_password(request, target)
    return _credentials_page(
        request,
        creds,
        title="Senha redefinida",
        description="As sessões abertas deste usuário foram encerradas. A senha anterior não funciona mais.",
        back_url=reverse("superadmin:users"),
        back_label="Voltar aos super admins",
    )


@super_admin_required
@require_POST
def user_set_active(request, user_id, active):
    target = _super_user_or_404(user_id)
    try:
        changed = set_user_active(request, target, active=active)
    except ServiceError as exc:
        messages.error(request, str(exc))
    else:
        if not changed:
            messages.info(request, "O usuário já está ativo." if active else "O usuário já está desativado.")
        elif active:
            messages.success(request, "Super admin reativado.")
        else:
            messages.success(request, "Super admin desativado. As sessões dele foram encerradas.")
    return redirect("superadmin:users")


# ---------------------------------------------------------------------------------------------
# Auditoria da plataforma
# ---------------------------------------------------------------------------------------------


@super_admin_required
def audit_log(request):
    form = AuditFilterForm(request.GET)
    form.is_valid()
    cleaned = form.cleaned_data
    page = Paginator(selectors.audit_queryset(cleaned), AUDIT_PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "superadmin/audit.html",
        {
            "form": form,
            "page_obj": page,
            "rows": selectors.decorate_audit_rows(page.object_list),
            "filtered": any(cleaned.get(key) for key in ("campaign", "action", "start", "end")),
        },
    )
