"""Páginas públicas do link de cadastro: /c/<code>/ (formulário), /obrigado/ e /privacidade/.

Sem login. Medidas: CSRF, honeypot, limite de taxa por IP e por código, resposta idêntica para links inexistentes,
desativados ou de campanha suspensa (404 amigável) e nunca expor dados de apoiadores já cadastrados.
"""

from __future__ import annotations

from functools import wraps

from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.auditlog.service import audit
from apps.core.constants import DEFAULT_WHATSAPP_OPTIN_TEXT, VoterSource
from apps.core.ratelimit import rate_limit
from apps.core.utils import client_ip
from apps.geo.geocode import geocode_voter_in_background

from .forms import PublicRegistrationForm
from .public import PublicRegistration, get_public_registration
from .services import register_public_voter
from .utils import safe_ip

DEFAULT_FORM_TITLE = "Cadastre-se e faça parte!"
RATE_PER_IP = (10, 10 * 60)  # 10 envios a cada 10 minutos por IP
RATE_PER_CODE = (120, 10 * 60)  # e 120 por link


def public_page(view):
    """Páginas /c/: sem cache e fora dos buscadores."""

    @wraps(view)
    @never_cache
    def wrapper(request, *args, **kwargs):
        response = view(request, *args, **kwargs)
        response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return response

    return wrapper


def invalid_link(request):
    return render(request, "voters/public_invalid.html", status=404)


def _context(reg: PublicRegistration, **extra) -> dict:
    campaign = reg.campaign
    return {
        "reg": reg,
        "campaign": campaign,
        "brand": reg.brand,
        "page_title": campaign.form_title.strip() or DEFAULT_FORM_TITLE,
        "page_message": campaign.form_message.strip(),
        **extra,
    }


@public_page
@require_http_methods(["GET", "POST"])
def public_form(request, code):
    reg = get_public_registration(code)
    if reg is None:
        return invalid_link(request)
    campaign = reg.campaign
    default_source = VoterSource.QRCODE.value if request.GET.get("src") == "qr" else VoterSource.LINK.value

    if request.method == "GET":
        form = PublicRegistrationForm(config=campaign.form_config, initial={"source": default_source})
        return render(request, "voters/public_form.html", _context(reg, form=form, optin_text=DEFAULT_WHATSAPP_OPTIN_TEXT))

    ip = client_ip(request)
    per_ip = rate_limit(f"pubreg:ip:{ip}", *RATE_PER_IP)
    per_code = rate_limit(f"pubreg:code:{reg.code}", *RATE_PER_CODE)
    form = PublicRegistrationForm(request.POST, config=campaign.form_config)

    if not (per_ip.ok and per_code.ok):
        wait = max(per_ip.retry_after_seconds, per_code.retry_after_seconds)
        form.add_error(None, f"Muitas tentativas em pouco tempo. Aguarde {max(1, wait // 60)} min e tente novamente.")
        return render(
            request, "voters/public_form.html", _context(reg, form=form, optin_text=DEFAULT_WHATSAPP_OPTIN_TEXT), status=429
        )

    # Honeypot: quem preenche o campo escondido é robô — responde como sucesso, sem gravar nada
    if (request.POST.get("website") or "").strip():
        return redirect("voters:public_thanks", code=reg.code)

    if not form.is_valid():
        return render(request, "voters/public_form.html", _context(reg, form=form, optin_text=DEFAULT_WHATSAPP_OPTIN_TEXT))

    result = register_public_voter(reg, form.cleaned_data, ip=safe_ip(ip), now=timezone.now())
    voter = result.voter
    if result.created:
        audit(
            "voter.public_register",
            request=request,
            user=reg.owner,
            campaign=campaign,
            entity="Voter",
            entity_id=voter.pk,
            details={"voter_id": str(voter.pk), "source": result.source},
        )
    else:
        audit(
            "voter.update",
            request=request,
            user=reg.owner,
            campaign=campaign,
            entity="Voter",
            entity_id=voter.pk,
            details={"voter_id": str(voter.pk), "via": "public_form", "filled": result.plan.filled if result.plan else []},
        )
    if result.needs_geocode:
        geocode_voter_in_background(voter.pk)

    url = reverse("voters:public_thanks", kwargs={"code": reg.code})
    return redirect(url if result.created else f"{url}?r=updated")


@public_page
@require_http_methods(["GET"])
def public_thanks(request, code):
    reg = get_public_registration(code)
    if reg is None:
        return invalid_link(request)
    return render(request, "voters/public_thanks.html", _context(reg, updated=request.GET.get("r") == "updated"))


@public_page
@require_http_methods(["GET"])
def public_privacy(request, code):
    reg = get_public_registration(code)
    if reg is None:
        return invalid_link(request)
    return render(request, "voters/public_privacy.html", _context(reg, optin_text=DEFAULT_WHATSAPP_OPTIN_TEXT))
