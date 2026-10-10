from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from apps.auditlog.service import audit
from apps.core.constants import CampaignStatus, Role
from apps.core.decorators import campaign_user_required, super_admin_required
from apps.core.permissions import can
from apps.core.phone import format_phone
from apps.core.qr import registration_url
from apps.core.ratelimit import rate_limit
from apps.core.utils import client_ip

from .forms import ChangePasswordForm, LoginForm, ProfileForm


def home_path_for(user) -> str:
    return "/super/" if user.role == Role.SUPER_ADMIN else "/painel/"


@never_cache
def login_view(request):
    if request.user.is_authenticated:
        return redirect(home_path_for(request.user))

    form = LoginForm(request.POST or None, initial={"next": request.GET.get("next", "")})
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].strip().lower()
        ip = client_ip(request)
        per_user = rate_limit(f"login:{ip}:{email}", 8, 15 * 60)
        per_ip = rate_limit(f"login-ip:{ip}", 40, 15 * 60)
        if not (per_user.ok and per_ip.ok):
            wait = max(per_user.retry_after_seconds, per_ip.retry_after_seconds)
            form.add_error(None, f"Muitas tentativas. Tente novamente em {max(1, wait // 60)} min.")
        else:
            user = authenticate(request, username=email, password=form.cleaned_data["password"])
            if user is None:
                from apps.accounts.models import User

                known = User.objects.filter(email=email).only("id", "campaign_id").first()
                audit("auth.login_failed", request=request, user=known, details={"reason": "credenciais"})
                form.add_error(None, "E-mail ou senha incorretos.")
            elif user.role != Role.SUPER_ADMIN and (user.campaign is None or user.campaign.status != CampaignStatus.ACTIVE):
                form.add_error(None, "Esta campanha está suspensa. Fale com o suporte do E-Find.")
            else:
                login(request, user)
                audit("auth.login", request=request, user=user)
                target = form.cleaned_data.get("next") or ""
                home = home_path_for(user)
                safe = (
                    target.startswith(home)
                    and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure())
                )
                return redirect(target if safe else home)
    return render(request, "accounts/login.html", {"form": form})


@require_POST
def logout_view(request):
    if request.user.is_authenticated:
        audit("auth.logout", request=request)
    logout(request)
    return redirect("/login/")


def _profile(request, template_context):
    user = request.user
    profile_form = ProfileForm(initial={"name": user.name, "phone": user.phone})
    password_form = ChangePasswordForm(user=user)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "profile":
            profile_form = ProfileForm(request.POST)
            if profile_form.is_valid():
                user.name = profile_form.cleaned_data["name"].strip()
                user.phone = profile_form.cleaned_data["phone"]
                user.save(update_fields=["name", "phone", "updated_at"])
                audit("user.update", request=request, entity="User", entity_id=user.pk, details={"self": True})
                messages.success(request, "Perfil atualizado.")
                return redirect(request.path)
        elif action == "password":
            password_form = ChangePasswordForm(request.POST, user=user)
            if password_form.is_valid():
                user.set_password(password_form.cleaned_data["new_password"])
                user.save(update_fields=["password", "updated_at"])
                update_session_auth_hash(request, user)  # mantém esta sessão; encerra as demais
                audit("auth.password_change", request=request)
                messages.success(request, "Senha alterada com sucesso. Outras sessões foram encerradas.")
                return redirect(request.path)

    context = {
        "profile_form": profile_form,
        "password_form": password_form,
        "parent": user.parent,
        "registration_link": registration_url(user.invite_code) if user.campaign_id else "",
        "can_my_link": can(request.perms, "meu_link", "view"),
        "phone_display": format_phone(user.phone),
        **template_context,
    }
    return render(request, "accounts/profile.html", context)


@campaign_user_required
def panel_profile(request):
    return _profile(request, {"is_super": False})


@super_admin_required
def super_profile(request):
    return _profile(request, {"is_super": True})
