"""Views provisórias dos módulos ainda não implementados (cada módulo substitui as suas)."""

from __future__ import annotations

from django.shortcuts import redirect, render

from .decorators import admin_required, campaign_user_required, module_permission_required, super_admin_required


def panel_stub(title: str, module: str | None = None, action: str = "view", admin: bool = False):
    def view(request, *args, **kwargs):
        return render(request, "components/placeholder.html", {"title": title})

    if admin:
        return admin_required(view)
    if module:
        return module_permission_required(module, action)(view)
    return campaign_user_required(view)


def super_stub(title: str):
    def view(request, *args, **kwargs):
        return render(request, "components/placeholder.html", {"title": title})

    return super_admin_required(view)


def public_stub(title: str):
    def view(request, *args, **kwargs):
        return render(request, "components/placeholder.html", {"title": title, "base_layout": "layouts/public.html"})

    return view


def redirect_home(request):
    return redirect("/painel/" if request.user.is_authenticated else "/login/")
