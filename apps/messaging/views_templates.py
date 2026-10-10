"""Modelos de mensagem (/painel/mensagens/modelos/). Modelos pertencem à campanha do usuário: toda busca passa por
`template_scope(user)` (nunca por id solto). Permissão: módulo "modelos" (view/create/edit/delete)."""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.auditlog.service import audit
from apps.core.constants import OPT_OUT_KEYWORDS, TemplateCategory, TemplateType
from apps.core.decorators import module_permission_required
from apps.core.permissions import can
from apps.core.template_vars import EXAMPLE_CONTEXT, TEMPLATE_VARIABLES

from .forms import TemplateForm, template_initial
from .logic import OPT_OUT_INSTRUCTION, TEMPLATE_BODY_MAX
from .models import MessageTemplate
from .queries import get_template_in_campaign, template_in_use_by, template_scope, templates_locked_by_broadcasts
from .whatsapp_format import plain_excerpt

LIST_URL = "/painel/mensagens/modelos/"
PER_PAGE = 24


def _template_or_404(request, pk) -> MessageTemplate:
    template = get_template_in_campaign(request.user, pk)
    if template is None:
        raise Http404("Modelo não encontrado.")
    return template


def _assign(template: MessageTemplate, data: dict) -> None:
    template.name = data["name"].strip()
    template.category = data["category"]
    template.type = data["type"]
    template.media_url = data.get("media_url") or ""
    template.body = data["body"]
    template.provider_template_name = data.get("provider_template_name") or ""
    template.provider_template_language = data.get("provider_template_language") or "pt_BR"
    template.provider_variables = list(data.get("provider_variables") or []) or None


def _editor_config(form: TemplateForm, *, read_only: bool) -> dict:
    """Dados do editor para o Alpine (json_script): variáveis, exemplos e estado inicial."""
    initial = {
        "body": form["body"].value() or "",
        "kind": form["type"].value() or TemplateType.TEXT,
        "mediaUrl": form["media_url"].value() or "",
        "rows": form.selected_variables,
    }
    return {
        "variables": TEMPLATE_VARIABLES,
        "example": EXAMPLE_CONTEXT,
        "optOutKeywords": list(OPT_OUT_KEYWORDS),
        "optOutInstruction": OPT_OUT_INSTRUCTION,
        "bodyMax": TEMPLATE_BODY_MAX,
        "readOnly": read_only,
        "initial": initial,
        "mediaLabels": {"IMAGE": "Imagem", "DOCUMENT": "Documento (PDF)", "VIDEO": "Vídeo"},
    }


# --------------------------------------------------------------------------------------------- listagem


@module_permission_required("modelos", "view")
def template_list(request):
    user = request.user
    query = (request.GET.get("q") or "").strip()[:100]
    category = request.GET.get("categoria") or ""
    queryset = template_scope(user)
    if category in TemplateCategory.values:
        queryset = queryset.filter(category=category)
    else:
        category = ""
    if query:
        queryset = queryset.filter(Q(name__icontains=query) | Q(body__icontains=query))

    page = Paginator(queryset.order_by("name"), PER_PAGE).get_page(request.GET.get("page"))
    locked = templates_locked_by_broadcasts(user.campaign_id)
    items = list(page.object_list)
    for template in items:
        template.excerpt = plain_excerpt(template.body, 170)
        template.is_locked = template.pk in locked
    return render(
        request,
        "messaging/template_list.html",
        {
            "page_obj": page,
            "templates": items,
            "q": query,
            "category": category,
            "categories": TemplateCategory.choices,
            "total_in_campaign": template_scope(user).count(),
            "can_create": can(request.perms, "modelos", "create"),
            "can_edit": can(request.perms, "modelos", "edit"),
            "can_delete": can(request.perms, "modelos", "delete"),
            "can_broadcast": can(request.perms, "disparos", "create"),
        },
    )


# --------------------------------------------------------------------------------------------- criar / editar


def _render_editor(request, form: TemplateForm, template: MessageTemplate | None, read_only: bool):
    return render(
        request,
        "messaging/template_form.html",
        {
            "form": form,
            "template_obj": template,
            "page_title": "Novo modelo" if template is None else ("Ver modelo" if read_only else "Editar modelo"),
            "read_only": read_only,
            "editor_config": _editor_config(form, read_only=read_only),
            "variables": TEMPLATE_VARIABLES,
            "list_url": LIST_URL,
        },
    )


@module_permission_required("modelos", "create")
def template_create(request):
    if request.method == "POST":
        form = TemplateForm(request.POST)
        if form.is_valid():
            template = MessageTemplate(campaign_id=request.user.campaign_id, created_by=request.user)
            _assign(template, form.cleaned_data)
            template.save()
            audit(
                "template.create",
                request=request,
                entity="MessageTemplate",
                entity_id=template.pk,
                details={"category": template.category, "type": template.type},
            )
            messages.success(request, "Modelo criado.")
            return redirect(LIST_URL)
        messages.error(request, "Corrija os campos destacados e tente de novo.")
    else:
        form = TemplateForm(
            initial={
                "category": TemplateCategory.INFORMATIVO,
                "type": TemplateType.TEXT,
                "provider_template_language": "pt_BR",
                "provider_variables": [],
            }
        )
    return _render_editor(request, form, None, read_only=False)


@module_permission_required("modelos", "view")
def template_edit(request, pk):
    template = _template_or_404(request, pk)
    can_edit = can(request.perms, "modelos", "edit")
    if request.method == "POST":
        if not can_edit:
            raise PermissionDenied("Você não tem permissão para editar modelos.")
        form = TemplateForm(request.POST)
        if form.is_valid():
            _assign(template, form.cleaned_data)
            template.save()
            audit(
                "template.update",
                request=request,
                entity="MessageTemplate",
                entity_id=template.pk,
                details={"category": template.category, "type": template.type},
            )
            messages.success(request, "Modelo atualizado.")
            return redirect(LIST_URL)
        messages.error(request, "Corrija os campos destacados e tente de novo.")
    else:
        form = TemplateForm(initial=template_initial(template), read_only=not can_edit)
    return _render_editor(request, form, template, read_only=not can_edit)


# --------------------------------------------------------------------------------------------- duplicar / excluir


@module_permission_required("modelos", "create")
@require_POST
def template_duplicate(request, pk):
    source = _template_or_404(request, pk)
    suffix = " (cópia)"
    copy = MessageTemplate.objects.create(
        campaign_id=request.user.campaign_id,
        created_by=request.user,
        name=f"{source.name[: 120 - len(suffix)]}{suffix}",
        category=source.category,
        type=source.type,
        body=source.body,
        media_url=source.media_url,
        provider_template_name=source.provider_template_name,
        provider_template_language=source.provider_template_language,
        provider_variables=source.provider_variables,
    )
    audit(
        "template.create",
        request=request,
        entity="MessageTemplate",
        entity_id=copy.pk,
        details={"duplicated_from": str(source.pk)},
    )
    messages.success(request, "Modelo duplicado. Ajuste o nome e o texto como quiser.")
    return redirect(f"{LIST_URL}{copy.pk}/")


@module_permission_required("modelos", "delete")
@require_POST
def template_delete(request, pk):
    with transaction.atomic():
        template = template_scope(request.user).select_for_update().filter(pk=pk).first()
        if template is None:
            raise Http404("Modelo não encontrado.")
        blocking = template_in_use_by(request.user.campaign_id, template.pk)
        if blocking is not None:
            messages.error(
                request,
                "Este modelo está em uso por um disparo agendado, em andamento ou pausado. "
                "Conclua ou cancele o disparo antes de excluir o modelo.",
            )
            return redirect(LIST_URL)
        template_id = template.pk
        template.delete()
    audit("template.delete", request=request, entity="MessageTemplate", entity_id=template_id)
    messages.success(request, "Modelo excluído.")
    return redirect(LIST_URL)
