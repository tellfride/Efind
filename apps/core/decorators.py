"""Autorização das views. TODA view de painel deve usar um destes decorators (ou o mixin equivalente).

    @module_permission_required("eleitores", "view")      # permissão no módulo (ADMIN sempre passa)
    @campaign_user_required                               # qualquer usuário de campanha logado
    @admin_required                                       # somente ADMIN da campanha
    @super_admin_required                                  # somente SUPER_ADMIN

Sem sessão → redireciona ao login (?next=). Logado sem permissão → 403 (página "sem permissão").
Para endpoints JSON/HTMX use `json_response=True`: devolve 401/403 em JSON em vez de redirecionar.
"""

from __future__ import annotations

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import redirect

from .constants import Role
from .permissions import can


def _unauthenticated(request, json_response: bool):
    if json_response or request.headers.get("HX-Request"):
        return JsonResponse({"error": "Sessão expirada. Faça login novamente."}, status=401)
    return redirect_to_login(request.get_full_path())


def _denied(request, json_response: bool, message: str = "Você não tem permissão para esta ação."):
    if json_response:
        return JsonResponse({"error": message}, status=403)
    raise PermissionDenied(message)


def campaign_user_required(view=None, *, json_response: bool = False):
    def decorator(fn):
        @wraps(fn)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return _unauthenticated(request, json_response)
            if user.role == Role.SUPER_ADMIN or request.campaign is None:
                if json_response:
                    return _denied(request, True, "Acesso restrito a usuários de campanha.")
                return redirect("/super/")
            return fn(request, *args, **kwargs)

        return wrapper

    return decorator(view) if view else decorator


def module_permission_required(module: str, action: str = "view", *, json_response: bool = False):
    def decorator(fn):
        @campaign_user_required(json_response=json_response)
        @wraps(fn)
        def wrapper(request, *args, **kwargs):
            if not can(request.perms, module, action):
                return _denied(request, json_response)
            return fn(request, *args, **kwargs)

        return wrapper

    return decorator


def admin_required(view=None, *, json_response: bool = False):
    def decorator(fn):
        @campaign_user_required(json_response=json_response)
        @wraps(fn)
        def wrapper(request, *args, **kwargs):
            if request.user.role != Role.ADMIN:
                return _denied(request, json_response, "Apenas administradores podem fazer isso.")
            return fn(request, *args, **kwargs)

        return wrapper

    return decorator(view) if view else decorator


def super_admin_required(view=None, *, json_response: bool = False):
    def decorator(fn):
        @wraps(fn)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return _unauthenticated(request, json_response)
            if user.role != Role.SUPER_ADMIN:
                if json_response:
                    return _denied(request, True, "Acesso restrito ao super admin.")
                return redirect("/painel/")
            return fn(request, *args, **kwargs)

        return wrapper

    return decorator(view) if view else decorator


class ModulePermissionMixin:
    """Mixin para CBVs: defina `permission_module` e (opcional) `permission_action`/`json_response`."""

    permission_module: str = ""
    permission_action: str = "view"
    json_response: bool = False

    def dispatch(self, request, *args, **kwargs):
        parent_dispatch = super().dispatch

        @module_permission_required(self.permission_module, self.permission_action, json_response=self.json_response)
        def guarded(req, *a, **kw):
            return parent_dispatch(req, *a, **kw)

        return guarded(request, *args, **kwargs)
