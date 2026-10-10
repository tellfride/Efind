"""Conexões de API do WhatsApp (/painel/whatsapp/). Toda leitura exige "whatsapp","view"; toda mutação exige
"whatsapp","edit". Conexões são sempre buscadas dentro da campanha do usuário logado (nunca por id solto) e
as credenciais nunca voltam ao navegador em claro (apenas `mask_secret`).
"""

from __future__ import annotations

import json
import math

from django.contrib import messages
from django.db import transaction
from django.http import Http404, HttpRequest, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.auditlog.service import audit
from apps.core.constants import ConnectionStatus, label_of
from apps.core.crypto import encrypt_json, random_token
from apps.core.decorators import module_permission_required
from apps.core.ratelimit import rate_limit

from .forms import ConnectionForm, TestMessageForm
from .models import WhatsAppConnection
from .providers.dialog360 import register_webhook
from .registry import PROVIDERS, get_provider_definition, webhook_url_for
from .services import (
    MAX_CONNECTIONS_PER_CAMPAIGN,
    PROVIDER_ICONS,
    STATUS_TONES,
    UNREADABLE_CREDENTIALS_MESSAGE,
    campaign_connections,
    count_active_broadcasts,
    decorate_connections,
    ensure_default_connection,
    get_campaign_connection,
    read_credentials,
    run_connection_test,
    send_test_message,
    set_default_connection,
)

WIZARD_STEPS = ["Provedor", "Credenciais", "Webhook", "Teste"]
LIST_URL = "whatsapp:connections"


# ------------------------------------------------------------------------------------------------ Helpers


def _connection_or_404(request: HttpRequest, pk) -> WhatsAppConnection:
    conn = get_campaign_connection(request.campaign.pk, pk)
    if conn is None:
        raise Http404("Conexão não encontrada.")
    return conn


def _wait_minutes(seconds: int) -> int:
    return max(1, math.ceil(seconds / 60))


def _throttle(request: HttpRequest, bucket: str, limit: int) -> int | None:
    """Limite por usuário (janela de 10 min). Devolve os minutos de espera quando estourou, senão None."""
    result = rate_limit(f"wa-{bucket}:{request.user.pk}", limit, 10 * 60)
    return None if result.ok else _wait_minutes(result.retry_after_seconds)


def _audit(request: HttpRequest, action: str, conn: WhatsAppConnection, **details) -> None:
    """Auditoria da conexão: apenas ids, provedor e nomes de campos (nunca segredos nem telefones)."""
    audit(action, request=request, entity="WhatsAppConnection", entity_id=conn.pk, details={"provider": conn.provider, **details})


def _status_payload(conn: WhatsAppConnection) -> dict:
    return {
        "status": conn.status,
        "status_label": label_of(ConnectionStatus, conn.status),
        "status_tone": STATUS_TONES.get(conn.status, "gray"),
        "last_error": conn.last_error,
        "phone_number": conn.phone_number,
    }


def _provider_cards() -> list[dict]:
    return [
        {
            "key": p.key,
            "label": p.label,
            "description": p.description,
            "official": p.official,
            "docs_url": p.docs_url,
            "requires_template": p.requires_approved_template,
            "icon": PROVIDER_ICONS.get(p.key, "plug-zap"),
        }
        for p in PROVIDERS
    ]


def _json(ok: bool, message: str, status: int = 200, **extra) -> JsonResponse:
    return JsonResponse({"ok": ok, "message": message, **extra}, status=status)


# ------------------------------------------------------------------------------------------------ Listagem


@module_permission_required("whatsapp", "view")
def connections(request):
    campaign = request.campaign
    items = decorate_connections(campaign_connections(campaign.pk), campaign.pk)
    return render(
        request,
        "whatsapp/connection_list.html",
        {
            "connections": items,
            "has_default": any(c.is_default for c in items),
            "connected_count": sum(1 for c in items if c.status == ConnectionStatus.CONNECTED),
            "max_connections": MAX_CONNECTIONS_PER_CAMPAIGN,
        },
    )


# ------------------------------------------------------------------------------------------------ Assistente


@module_permission_required("whatsapp", "edit")
def connection_new(request):
    """Passos 1 (provedor) e 2 (credenciais). O rascunho é salvo no fim do passo 2."""
    campaign = request.campaign
    key = (request.POST.get("provider") if request.method == "POST" else request.GET.get("provider")) or ""
    definition = get_provider_definition(key) if key else None

    if definition is None:
        if request.method == "POST":
            messages.error(request, "Escolha um provedor para continuar.")
            return redirect("whatsapp:connection_new")
        return render(
            request,
            "whatsapp/wizard_provider.html",
            {"providers": _provider_cards(), "steps": WIZARD_STEPS, "current_step": 1},
        )

    form = ConnectionForm(request.POST or None, definition=definition)
    if request.method == "POST" and form.is_valid():
        if campaign_connections(campaign.pk).count() >= MAX_CONNECTIONS_PER_CAMPAIGN:
            form.add_error(
                None, f"Limite de {MAX_CONNECTIONS_PER_CAMPAIGN} conexões por campanha atingido. Exclua conexões sem uso."
            )
        else:
            try:
                encrypted = encrypt_json(form.credentials)
            except RuntimeError:
                form.add_error(
                    None, "A chave de criptografia do servidor (ENCRYPTION_KEY) não está configurada. Fale com o suporte."
                )
            else:
                with transaction.atomic():
                    conn = WhatsAppConnection.objects.create(
                        campaign=campaign,
                        name=form.cleaned_data["name"],
                        provider=definition.key,
                        status=ConnectionStatus.DRAFT,
                        phone_number=form.cleaned_data["phone_number"],
                        credentials=encrypted,
                        webhook_token=random_token(),
                        rate_per_minute=form.cleaned_data["rate_per_minute"],
                    )
                    ensure_default_connection(campaign.pk)
                _audit(request, "whatsapp.connection_create", conn, name=conn.name)
                messages.success(request, "Rascunho salvo. Agora configure o webhook.")
                return redirect("whatsapp:connection_webhook", pk=conn.pk)

    return render(
        request,
        "whatsapp/wizard_credentials.html",
        {
            "form": form,
            "definition": definition,
            "connection": None,
            "steps": WIZARD_STEPS,
            "current_step": 2,
            "provider_icon": PROVIDER_ICONS.get(definition.key, "plug-zap"),
        },
    )


@module_permission_required("whatsapp", "edit")
def connection_edit(request, pk):
    campaign = request.campaign
    conn = _connection_or_404(request, pk)
    definition = get_provider_definition(conn.provider)
    if definition is None:
        raise Http404("Provedor indisponível.")
    existing, unreadable = read_credentials(conn)

    initial = {"name": conn.name, "phone_number": conn.phone_number, "rate_per_minute": conn.rate_per_minute}
    form = ConnectionForm(request.POST or None, definition=definition, existing=existing, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            encrypted = encrypt_json(form.credentials) if (form.changed_fields or unreadable) else conn.credentials
        except RuntimeError:
            form.add_error(None, "A chave de criptografia do servidor (ENCRYPTION_KEY) não está configurada. Fale com o suporte.")
        else:
            data = form.cleaned_data
            changed = [
                *(f for f, now_value in (("name", data["name"]), ("phone_number", data["phone_number"]), ("rate_per_minute", data["rate_per_minute"]))
                  if getattr(conn, f) != now_value),
                *(f"credentials.{name}" for name in form.changed_fields),
            ]
            conn.name = data["name"]
            conn.phone_number = data["phone_number"]
            conn.rate_per_minute = data["rate_per_minute"]
            conn.credentials = encrypted
            conn.save(update_fields=["name", "phone_number", "rate_per_minute", "credentials", "updated_at"])

            message = "Conexão atualizada." if changed else "Nenhuma alteração."
            level = messages.success
            # Credenciais novas invalidam o último teste: conexões em uso são testadas de novo na hora
            if form.changed_fields and conn.status in (ConnectionStatus.CONNECTED, ConnectionStatus.ERROR):
                conn, result = run_connection_test(conn)
                if result.ok:
                    message = "Credenciais atualizadas e conexão testada com sucesso."
                else:
                    message, level = f"Credenciais salvas, mas o teste falhou: {result.message}", messages.warning
            if changed:
                _audit(request, "whatsapp.connection_update", conn, changed_fields=changed, status=conn.status)
            level(request, message)
            return redirect(LIST_URL)

    return render(
        request,
        "whatsapp/wizard_credentials.html",
        {
            "form": form,
            "definition": definition,
            "connection": conn,
            "credentials_unreadable": unreadable,
            "steps": WIZARD_STEPS,
            "current_step": 2,
            "provider_icon": PROVIDER_ICONS.get(definition.key, "plug-zap"),
        },
    )


@module_permission_required("whatsapp", "edit")
def connection_webhook(request, pk):
    """Passo 3: URL de callback e token de verificação para configurar no provedor."""
    conn = _connection_or_404(request, pk)
    definition = get_provider_definition(conn.provider)
    if definition is None:
        raise Http404("Provedor indisponível.")
    webhook_url = webhook_url_for(conn.webhook_token)
    return render(
        request,
        "whatsapp/wizard_webhook.html",
        {
            "connection": conn,
            "definition": definition,
            "webhook_url": webhook_url,
            "webhook_is_https": webhook_url.startswith("https://"),
            "uses_verify_token": definition.handle_verification is not None,
            "is_sandbox": definition.key == "SANDBOX",
            "can_register_webhook": definition.key == "DIALOG360",
            "steps": WIZARD_STEPS,
            "current_step": 3,
        },
    )


@module_permission_required("whatsapp", "edit")
def connection_check(request, pk):
    """Passo 4: testar a conexão e (opcionalmente) enviar uma mensagem de teste."""
    conn = _connection_or_404(request, pk)
    definition = get_provider_definition(conn.provider)
    if definition is None:
        raise Http404("Provedor indisponível.")
    allow_template = conn.provider == "META_CLOUD"
    return render(
        request,
        "whatsapp/wizard_test.html",
        {
            "connection": conn,
            "definition": definition,
            "status_tone": STATUS_TONES.get(conn.status, "gray"),
            "test_form": TestMessageForm(allow_template=allow_template),
            "allow_template": allow_template,
            "is_sandbox": definition.key == "SANDBOX",
            "steps": WIZARD_STEPS,
            "current_step": 4,
        },
    )


# ------------------------------------------------------------------------------------------------ Ações (POST + redirect)


@module_permission_required("whatsapp", "edit")
@require_POST
def connection_test(request, pk):
    conn = _connection_or_404(request, pk)
    wait = _throttle(request, "test", 30)
    if wait:
        messages.error(request, f"Muitos testes seguidos. Tente novamente em {wait} min.")
        return redirect(LIST_URL)
    conn, result = run_connection_test(conn, keep_disabled=True)
    _audit(request, "whatsapp.connection_test", conn, kind="connection", ok=result.ok)
    (messages.success if result.ok else messages.error)(request, result.message)
    return redirect(LIST_URL)


@module_permission_required("whatsapp", "edit")
@require_POST
def connection_default(request, pk):
    conn = _connection_or_404(request, pk)
    if conn.status != ConnectionStatus.CONNECTED:
        messages.error(request, "Teste a conexão com sucesso antes de defini-la como padrão.")
    elif conn.is_default:
        messages.info(request, "Esta já é a conexão padrão.")
    else:
        set_default_connection(conn)
        _audit(request, "whatsapp.connection_update", conn, changed_fields=["is_default"], is_default=True)
        messages.success(request, f"“{conn.name}” agora é a conexão padrão dos disparos.")
    return redirect(LIST_URL)


@module_permission_required("whatsapp", "edit")
@require_POST
def connection_disable(request, pk):
    conn = _connection_or_404(request, pk)
    if conn.status == ConnectionStatus.DISABLED:
        messages.info(request, "A conexão já está desativada.")
        return redirect(LIST_URL)
    conn.status = ConnectionStatus.DISABLED
    conn.is_default = False
    conn.save(update_fields=["status", "is_default", "updated_at"])
    ensure_default_connection(conn.campaign_id)
    _audit(request, "whatsapp.connection_update", conn, changed_fields=["status"], status=conn.status)
    messages.success(request, "Conexão desativada. Ela não será usada em novos envios.")
    return redirect(LIST_URL)


@module_permission_required("whatsapp", "edit")
@require_POST
def connection_enable(request, pk):
    conn = _connection_or_404(request, pk)
    if conn.status != ConnectionStatus.DISABLED:
        messages.info(request, "A conexão já está ativa.")
        return redirect(LIST_URL)
    # Reativar = testar de novo: CONNECTED se passar, ERROR (com o motivo) se falhar
    conn, result = run_connection_test(conn)
    _audit(request, "whatsapp.connection_update", conn, changed_fields=["status"], status=conn.status)
    if result.ok:
        messages.success(request, "Conexão reativada e testada com sucesso.")
    else:
        messages.warning(request, f"Conexão reativada, mas o teste falhou: {result.message}")
    return redirect(LIST_URL)


@module_permission_required("whatsapp", "edit")
@require_POST
def connection_delete(request, pk):
    conn = _connection_or_404(request, pk)
    active = count_active_broadcasts(conn.campaign_id, conn.pk)
    if active:
        messages.error(
            request,
            f"Esta conexão está sendo usada por {active} disparo(s) em andamento, agendado(s) ou pausado(s). "
            "Conclua ou cancele esses disparos antes de excluí-la.",
        )
        return redirect(LIST_URL)
    name, conn_id, provider = conn.name, conn.pk, conn.provider
    conn.delete()
    ensure_default_connection(request.campaign.pk)
    audit(
        "whatsapp.connection_delete",
        request=request,
        entity="WhatsAppConnection",
        entity_id=conn_id,
        details={"provider": provider, "name": name},
    )
    messages.success(request, f"Conexão “{name}” excluída.")
    return redirect(LIST_URL)


# ------------------------------------------------------------------------------------------------ API JSON (assistente)


@module_permission_required("whatsapp", "edit", json_response=True)
@require_POST
def api_test_connection(request, pk):
    conn = _connection_or_404(request, pk)
    wait = _throttle(request, "test", 30)
    if wait:
        return _json(False, f"Muitos testes seguidos. Tente novamente em {wait} min.", status=429)
    conn, result = run_connection_test(conn, keep_disabled=True)
    _audit(request, "whatsapp.connection_test", conn, kind="connection", ok=result.ok)
    return JsonResponse(
        {
            "ok": result.ok,
            "message": result.message,
            **_status_payload(conn),
            "last_tested_at": timezone.localtime(conn.last_tested_at).strftime("%d/%m/%Y %H:%M") if conn.last_tested_at else "",
        }
    )


def _request_data(request: HttpRequest):
    """Corpo da requisição como mapeamento (JSON ou formulário); None se o JSON for inválido."""
    if request.content_type == "application/json":
        try:
            data = json.loads(request.body or b"{}")
        except ValueError:
            return None
        return data if isinstance(data, dict) else None
    return request.POST


@module_permission_required("whatsapp", "edit", json_response=True)
@require_POST
def api_send_test_message(request, pk):
    conn = _connection_or_404(request, pk)
    data = _request_data(request)
    if data is None:
        return _json(False, "Requisição inválida.", status=400)
    form = TestMessageForm(data, allow_template=conn.provider == "META_CLOUD")
    if not form.is_valid():
        errors = {name: errs[0] for name, errs in form.errors.items()}
        return _json(False, next(iter(errors.values()), "Dados inválidos."), status=400, errors=errors)
    if conn.status == ConnectionStatus.DISABLED:
        return _json(False, "Ative a conexão antes de enviar uma mensagem de teste.", status=400)
    wait = _throttle(request, "test-msg", 10)
    if wait:
        return _json(False, f"Limite de mensagens de teste atingido. Tente novamente em {wait} min.", status=429)

    use_template = bool(form.cleaned_data.get("use_template"))
    result = send_test_message(conn, form.cleaned_data["to"], form.cleaned_data["text"], use_template)
    _audit(request, "whatsapp.connection_test", conn, kind="message", ok=result.ok, template=use_template)
    if not result.ok:
        return _json(False, result.error or "O provedor recusou a mensagem.", status=400)
    message = (
        "Envio simulado com sucesso — nenhuma mensagem real foi enviada."
        if conn.provider == "SANDBOX"
        else "Mensagem aceita pelo provedor. Confira o WhatsApp do número informado."
    )
    return _json(True, message)


@module_permission_required("whatsapp", "edit", json_response=True)
@require_POST
def api_register_webhook(request, pk):
    """Registra a URL de callback na 360dialog (única API de provedor que permite configurar o webhook)."""
    conn = _connection_or_404(request, pk)
    if conn.provider != "DIALOG360":
        return _json(False, "O registro automático de webhook está disponível apenas para a 360dialog.", status=400)
    url = webhook_url_for(conn.webhook_token)
    if not url.startswith("https://"):
        return _json(
            False, "Configure APP_URL com o endereço público HTTPS do E-Find antes de registrar o webhook.", status=400
        )
    credentials, unreadable = read_credentials(conn)
    if unreadable:
        return _json(False, UNREADABLE_CREDENTIALS_MESSAGE, status=400)
    ok, message = register_webhook(credentials, url)
    if ok:
        _audit(request, "whatsapp.connection_update", conn, changed_fields=["webhook"], webhook_registered=True)
    return _json(ok, message, status=200 if ok else 400)
