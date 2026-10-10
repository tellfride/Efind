"""Equipe: /painel/equipe/ (resumo, hierarquia, lista), cadastro, perfil do membro e ações.

Segurança: toda view começa com o decorator de permissão do módulo "equipe"; o membro alvo vem SEMPRE de
`get_member_in_scope` (404 fora da campanha/escopo) e ações de gestão exigem `can_manage_member`. Ações que mudam
estado só por POST (CSRF). Coordenador só cria/edita cabos da própria rede, e o servidor impõe isso
independentemente do que o formulário enviar.
"""

from __future__ import annotations

import datetime as dt

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from apps.core.access import get_member_in_scope, team_scope, voter_scope
from apps.core.constants import Role
from apps.core.decorators import module_permission_required
from apps.core.permissions import can
from apps.core.qr import app_url, qr_png_data_url, registration_url
from apps.core.phone import whatsapp_link

from . import queries
from .forms import MemberCreateForm, MemberDeleteForm, MemberEditForm, MoveMemberForm
from .listing import (
    SORT_CHOICES,
    STATUS_CHOICES,
    build_tree,
    filter_rows,
    load_team_rows,
    parse_list_filters,
    roles_hint,
    sort_rows,
    summarize,
)
from .rules import (
    OPERATION_DELETE,
    build_access_message,
    can_manage_member,
    check_self_and_last_admin,
    goal_percent,
    goal_tone,
    parent_options_for,
    same_id,
)
from .services import (
    TeamError,
    create_member,
    delete_member,
    move_member,
    regenerate_invite,
    reset_member_password,
    set_member_active,
    update_member,
)

PAGE_SIZE = 25
LIST_PARAMS = ("q", "papel", "coord", "status", "ordem", "page")


def _member_or_404(request, member_id):
    member = get_member_in_scope(request.user, member_id)
    if member is None:
        raise Http404("Membro não encontrado.")
    return member


def _require_manage(request, member) -> None:
    if not can_manage_member(request.user, member):
        raise PermissionDenied("Você não tem permissão para gerenciar este membro.")


def _can_register_members(request) -> bool:
    """Cabos nunca cadastram membros, mesmo que o módulo lhes conceda "criar"."""
    return request.user.role in (Role.ADMIN, Role.COORDENADOR) and can(request.perms, "equipe", "create")


# --------------------------------------------------------------------------------------------
# Lista / hierarquia
# --------------------------------------------------------------------------------------------


@module_permission_required("equipe", "view")
def team_list(request):
    user = request.user
    rows = load_team_rows(user)
    summary = summarize(rows)
    coordinators = [r for r in rows if r.role == Role.COORDENADOR]
    filters = parse_list_filters(request.GET, {str(r.id) for r in coordinators})
    filtered = sort_rows(filter_rows(rows, filters), filters.sort)
    page_obj = Paginator(filtered, PAGE_SIZE).get_page(request.GET.get("page"))
    initial_view = "lista" if (request.GET.get("vista") == "lista" or any(p in request.GET for p in LIST_PARAMS)) else "hierarquia"

    context = {
        "summary": summary,
        "roles_hint": roles_hint(summary),
        "inactive_hint": (
            f"{summary.inactive} inativo{'s' if summary.inactive != 1 else ''}" if summary.inactive else "Todos com acesso liberado"
        ),
        "tree": build_tree(rows),
        "page_obj": page_obj,
        "filters": filters,
        "total_filtered": len(filtered),
        "coordinators": sorted(coordinators, key=lambda r: r.sort_name),
        "role_choices": [(r.value, r.label) for r in (Role.ADMIN, Role.COORDENADOR, Role.CABO)],
        "status_choices": STATUS_CHOICES,
        "sort_choices": SORT_CHOICES,
        "initial_view": initial_view,
        "can_create": _can_register_members(request),
        "show_coordinator_filter": user.role == Role.ADMIN and bool(coordinators),
    }
    return render(request, "team/list.html", context)


# --------------------------------------------------------------------------------------------
# Cadastro
# --------------------------------------------------------------------------------------------


def _render_credentials(request, member, password: str, *, reset: bool):
    """Mostra o acesso UMA vez. A senha vai só nesta resposta (sem cache) e nunca é gravada em texto."""
    login_url = app_url("/login/")
    link = registration_url(member.invite_code)
    message = build_access_message(
        member_name=member.name,
        campaign_name=request.campaign.ballot_name,
        role=member.role,
        login_url=login_url,
        email=member.email,
        password=password,
        registration_url=None if reset else link,
        reset=reset,
    )
    context = {
        "member": member,
        "password": password,
        "login_url": login_url,
        "registration_link": link,
        "access_message": message,
        "whatsapp_url": whatsapp_link(member.phone, message) if member.phone else "",
        "reset": reset,
    }
    return render(request, "team/credentials.html", context)


@never_cache
@module_permission_required("equipe", "create")
def member_create(request):
    actor = request.user
    if not _can_register_members(request):
        raise PermissionDenied("Cabos eleitorais não podem cadastrar membros na equipe.")

    form = MemberCreateForm(request.POST or None, actor=actor, initial={"role": Role.CABO.value})
    if request.method == "POST" and form.is_valid():
        try:
            member, password = create_member(request, form.cleaned_data)
        except TeamError as exc:
            form.add_error(exc.field if exc.field in form.fields else None, exc.message)
        else:
            return _render_credentials(request, member, password, reset=False)

    return render(request, "team/form.html", {"form": form, "form_config": form.alpine_config, "is_admin": form.is_admin})


# --------------------------------------------------------------------------------------------
# Perfil do membro
# --------------------------------------------------------------------------------------------


def _detail_context(request, member, *, edit_form=None, delete_form=None, edit_open=False, delete_open=False):
    user = request.user
    perms = request.perms
    is_self = same_id(member.pk, user.pk)
    manageable = can_manage_member(user, member)
    can_edit = can(perms, "equipe", "edit")
    can_delete = can(perms, "equipe", "delete")

    # Estatísticas (somente eleitores do escopo do visualizador — o membro está no escopo, então são todos os dele)
    own = voter_scope(user).filter(registered_by_id=member.pk)
    local_now = timezone.localtime()
    today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    now = timezone.now()
    stats = own.aggregate(
        total=Count("id"),
        today=Count("id", filter=Q(created_at__gte=today_start)),
        d7=Count("id", filter=Q(created_at__gte=now - dt.timedelta(days=7))),
        d30=Count("id", filter=Q(created_at__gte=now - dt.timedelta(days=30))),
    )
    top = list(
        own.exclude(neighborhood="").order_by().values("neighborhood").annotate(n=Count("id")).order_by("-n", "neighborhood")[:5]
    )
    top_max = top[0]["n"] if top else 0
    neighborhoods = [
        {"name": t["neighborhood"], "count": t["n"], "pct": round(t["n"] / top_max * 100) if top_max else 0} for t in top
    ]
    can_see_voters = can(perms, "eleitores", "view")
    recent = (
        list(own.order_by("-created_at").values("id", "name", "neighborhood", "created_at")[:10]) if can_see_voters else []
    )

    # Cabos do coordenador (contagens em UMA consulta)
    children = []
    if member.role in (Role.COORDENADOR, Role.ADMIN):
        kids = list(team_scope(user).filter(parent_id=member.pk).order_by("name"))
        counts = {
            r["registered_by_id"]: r["n"]
            for r in voter_scope(user)
            .filter(registered_by_id__in=[k.pk for k in kids])
            .order_by()
            .values("registered_by_id")
            .annotate(n=Count("id"))
        }
        children = [
            {
                "member": k,
                "voters": counts.get(k.pk, 0),
                "goal_percent": goal_percent(counts.get(k.pk, 0), k.goal),
                "goal_tone": goal_tone(goal_percent(counts.get(k.pk, 0), k.goal)),
            }
            for k in kids
        ]

    percent = goal_percent(stats["total"], member.goal)
    link = registration_url(member.invite_code)

    is_last_admin = (
        member.role == Role.ADMIN and member.is_active and queries.other_active_admins(user.campaign_id, member.pk) == 0
    )
    show_edit = manageable and can_edit
    show_active_toggle = show_edit and not is_self and not (member.is_active and is_last_admin)
    show_delete = manageable and can_delete and not is_self and not is_last_admin

    move_options = []
    if user.role == Role.ADMIN and show_edit and member.role != Role.ADMIN:
        candidates = [c for c in queries.parent_candidates(user.campaign_id) if not same_id(c.pk, member.pk)]
        move_options = parent_options_for(
            member.role, candidates, queries.has_active_coordinators(user.campaign_id, exclude_pk=member.pk)
        )

    if show_edit and edit_form is None:
        edit_form = MemberEditForm(actor=user, target=member)
    if show_delete and delete_form is None:
        delete_form = MemberDeleteForm(actor=user, target=member)

    return {
        "member": member,
        "parent": member.parent if member.parent_id else None,
        "is_self": is_self,
        "stats": stats,
        "goal_percent": percent,
        "goal_tone": goal_tone(percent),
        "goal_remaining": max(member.goal - stats["total"], 0) if member.goal else None,
        "neighborhoods": neighborhoods,
        "recent_voters": recent,
        "can_see_voters": can_see_voters,
        "children": children,
        "registration_link": link,
        "voters_url": f"/painel/eleitores/?cabo={member.pk}",
        "qr_data_url": qr_png_data_url(registration_url(member.invite_code, "qr")),
        "show_edit": show_edit,
        "show_active_toggle": show_active_toggle,
        "show_reset_password": show_edit and not is_self,
        "show_regenerate": can_edit and (is_self or manageable),
        "show_delete": show_delete,
        "is_last_admin": is_last_admin,
        "move_options": move_options,
        "edit_form": edit_form,
        "edit_config": edit_form.alpine_config if edit_form is not None else None,
        "edit_open": edit_open,
        "delete_form": delete_form,
        "delete_open": delete_open,
    }


@module_permission_required("equipe", "view")
def member_detail(request, member_id):
    member = _member_or_404(request, member_id)
    return render(request, "team/detail.html", _detail_context(request, member))


def _detail_redirect(member):
    return redirect(reverse("team:detail", args=[member.pk]))


@module_permission_required("equipe", "edit")
@require_POST
def member_update(request, member_id):
    member = _member_or_404(request, member_id)
    _require_manage(request, member)
    form = MemberEditForm(request.POST, actor=request.user, target=member)
    if form.is_valid():
        try:
            changed = update_member(request, member, form.cleaned_data)
        except TeamError as exc:
            form.add_error(exc.field if exc.field in form.fields else None, exc.message)
        else:
            if changed:
                messages.success(request, "Dados atualizados.")
            else:
                messages.info(request, "Nenhuma alteração para salvar.")
            return _detail_redirect(member)
    return render(request, "team/detail.html", _detail_context(request, member, edit_form=form, edit_open=True))


@module_permission_required("equipe", "edit")
@require_POST
def member_move(request, member_id):
    member = _member_or_404(request, member_id)
    _require_manage(request, member)
    form = MoveMemberForm(request.POST)
    if not form.is_valid():
        messages.error(request, form.errors["parent"][0])
        return _detail_redirect(member)
    try:
        moved = move_member(request, member, form.cleaned_data["parent"])
    except TeamError as exc:
        messages.error(request, exc.message)
    else:
        if moved:
            messages.success(
                request, "Membro movido. Os eleitores cadastrados por ele passam a aparecer na rede do novo responsável."
            )
        else:
            messages.info(request, "O membro já está com este responsável.")
    return _detail_redirect(member)


def _toggle_active(request, member_id, active: bool):
    member = _member_or_404(request, member_id)
    _require_manage(request, member)
    try:
        changed = set_member_active(request, member, active)
    except TeamError as exc:
        messages.error(request, exc.message)
    else:
        if not changed:
            messages.info(request, "O membro já está ativo." if active else "O membro já está desativado.")
        elif active:
            messages.success(request, "Acesso reativado.")
        else:
            messages.success(request, "Acesso desativado. Ele não consegue mais entrar e o link de cadastro foi suspenso.")
    return _detail_redirect(member)


@module_permission_required("equipe", "edit")
@require_POST
def member_activate(request, member_id):
    return _toggle_active(request, member_id, True)


@module_permission_required("equipe", "edit")
@require_POST
def member_deactivate(request, member_id):
    return _toggle_active(request, member_id, False)


@never_cache
@module_permission_required("equipe", "edit")
@require_POST
def member_reset_password(request, member_id):
    member = _member_or_404(request, member_id)
    _require_manage(request, member)
    try:
        password = reset_member_password(request, member)
    except TeamError as exc:
        messages.error(request, exc.message)
        return _detail_redirect(member)
    return _render_credentials(request, member, password, reset=True)


@module_permission_required("equipe", "edit")
@require_POST
def member_regenerate_link(request, member_id):
    member = _member_or_404(request, member_id)
    if not same_id(member.pk, request.user.pk):
        _require_manage(request, member)
    try:
        regenerate_invite(request, member)
    except TeamError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, "Novo link gerado. O link e o QR Code anteriores deixaram de funcionar.")
    return _detail_redirect(member)


@module_permission_required("equipe", "delete")
@require_POST
def member_delete(request, member_id):
    member = _member_or_404(request, member_id)
    _require_manage(request, member)
    # Travas antes de pedir destino de eleitores/equipe: o próprio usuário e o último administrador
    others = queries.other_active_admins(request.user.campaign_id, member.pk) if member.role == Role.ADMIN else 1
    blocked = check_self_and_last_admin(OPERATION_DELETE, request.user.pk, member, others)
    if blocked:
        messages.error(request, blocked)
        return _detail_redirect(member)
    form = MemberDeleteForm(request.POST, actor=request.user, target=member)
    if form.is_valid():
        try:
            result = delete_member(request, member, form.cleaned_data)
        except TeamError as exc:
            if exc.field in form.fields:
                form.add_error(exc.field, exc.message)
            else:
                messages.error(request, exc.message)
                return _detail_redirect(member)
        else:
            moved = result["voters_transferred"]
            messages.success(
                request,
                f"Membro excluído. {moved} eleitor{'es' if moved != 1 else ''} transferido{'s' if moved != 1 else ''}."
                if moved
                else "Membro excluído.",
            )
            return redirect(reverse("team:list"))
    return render(request, "team/detail.html", _detail_context(request, member, delete_form=form, delete_open=True))
