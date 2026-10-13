"""Contexto de campanha por requisição.

Define em toda requisição de usuário autenticado:
  - request.campaign : Campaign do usuário (None para SUPER_ADMIN)
  - request.perms    : PermissionSet efetivo (calculado sob demanda, 1x por requisição)
E encerra a sessão de quem pertence a uma campanha suspensa.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import logout
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils.functional import SimpleLazyObject

from .constants import Role


# Com senha provisória pendente, o usuário só alcança a troca de senha (perfil), o logout e os arquivos estáticos
_PASSWORD_CHANGE_PATHS = ("/painel/perfil/", "/super/perfil/", "/logout/", "/static/", "/favicon.ico")


class CampaignContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from apps.accounts.services import permissions_for

        request.campaign = None
        user = request.user
        if user.is_authenticated:
            if user.role != Role.SUPER_ADMIN:
                campaign = user.campaign
                if campaign is None or not campaign.is_active:
                    logout(request)
                    messages.error(request, "Esta campanha está suspensa. Fale com o suporte do E-Find.")
                    return redirect("/login/")
                request.campaign = campaign
            request.perms = SimpleLazyObject(lambda: permissions_for(user))
            if user.must_change_password and not request.path.startswith(_PASSWORD_CHANGE_PATHS):
                if request.path.startswith("/api/") or request.headers.get("HX-Request"):
                    return JsonResponse({"error": "Defina uma nova senha antes de continuar."}, status=403)
                messages.warning(request, "Você entrou com uma senha provisória. Defina uma nova senha para continuar.")
                return redirect("/super/perfil/" if user.role == Role.SUPER_ADMIN else "/painel/perfil/")
        else:
            request.perms = {}
        return self.get_response(request)
