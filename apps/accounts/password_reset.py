"""Recuperação de senha por e-mail: links de uso único (validade em settings.PASSWORD_RESET_TIMEOUT, 1 h).

Regras de segurança:
- A resposta é SEMPRE a mesma (e-mail existente ou não, limite excedido ou falha de envio): não revela quem tem conta.
- Limite de pedidos por IP e por e-mail (evita uso como bomba de e-mails).
- O link usa o domínio de settings.APP_URL, nunca o cabeçalho Host da requisição (evita envenenamento de link).
- Só funciona quando há e-mail configurado (settings.PASSWORD_RESET_ENABLED); caso contrário, 404.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.contrib.auth.views import PasswordResetConfirmView, PasswordResetView
from django.http import Http404, HttpResponseRedirect
from django.urls import reverse_lazy

from apps.auditlog.service import audit
from apps.core.forms import StyledFormMixin
from apps.core.ratelimit import rate_limit
from apps.core.utils import client_ip

logger = logging.getLogger(__name__)

RESET_REQUESTS_PER_IP = 10  # por hora
RESET_REQUESTS_PER_EMAIL = 3  # por hora


class StyledPasswordResetForm(StyledFormMixin, PasswordResetForm):
    pass


class StyledSetPasswordForm(StyledFormMixin, SetPasswordForm):
    """Mesma regra de senha do painel: validadores do Django + letras e números."""

    def clean(self):
        cleaned = super().clean()
        password = self.cleaned_data.get("new_password1") or ""
        if password and not (any(c.isalpha() for c in password) and any(c.isdigit() for c in password)):
            self.add_error("new_password1", "A senha deve conter letras e números.")
        return cleaned


class _EnabledOnlyMixin:
    def dispatch(self, request, *args, **kwargs):
        if not settings.PASSWORD_RESET_ENABLED:
            raise Http404
        return super().dispatch(request, *args, **kwargs)


class RequestPasswordResetView(_EnabledOnlyMixin, PasswordResetView):
    template_name = "accounts/password_reset_form.html"
    email_template_name = "accounts/emails/password_reset.txt"
    subject_template_name = "accounts/emails/password_reset_subject.txt"
    form_class = StyledPasswordResetForm
    success_url = reverse_lazy("accounts:password_reset_done")

    def form_valid(self, form):
        email = form.cleaned_data["email"].strip().lower()
        ip_ok = rate_limit(f"pwreset-ip:{client_ip(self.request)}", RESET_REQUESTS_PER_IP, 3600).ok
        email_ok = rate_limit(f"pwreset-email:{email}", RESET_REQUESTS_PER_EMAIL, 3600).ok
        if ip_ok and email_ok:
            base = urlparse(settings.APP_URL)
            try:
                form.save(
                    domain_override=base.netloc,
                    use_https=base.scheme == "https",
                    token_generator=self.token_generator,
                    from_email=None,
                    email_template_name=self.email_template_name,
                    subject_template_name=self.subject_template_name,
                    request=self.request,
                    extra_email_context={"valid_minutes": settings.PASSWORD_RESET_TIMEOUT // 60},
                )
            except Exception:  # noqa: BLE001 — SMTP fora do ar: mesma resposta, erro só no log (sem e-mail/dados pessoais)
                logger.exception("Falha ao enviar o e-mail de redefinição de senha")
        return HttpResponseRedirect(self.get_success_url())


class ConfirmPasswordResetView(_EnabledOnlyMixin, PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    form_class = StyledSetPasswordForm
    success_url = reverse_lazy("accounts:password_reset_complete")
    post_reset_login = False

    def form_valid(self, form):
        response = super().form_valid(form)  # grava a nova senha (isso também encerra as sessões antigas)
        user = form.user
        if user.must_change_password:
            type(user).objects.filter(pk=user.pk).update(must_change_password=False)
        audit("auth.password_reset_email", request=self.request, user=user)
        return response
