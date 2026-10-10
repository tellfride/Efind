"""Meu link: link pessoal de cadastro, QR Code, estatísticas pessoais e cartaz para impressão."""

from __future__ import annotations

from datetime import timedelta

from django.shortcuts import render
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from apps.core.decorators import module_permission_required
from apps.core.permissions import can
from apps.core.qr import qr_png_data_url, qr_svg, registration_url
from apps.core.utils import slugify

from .models import Voter
from .public import brand_for, share_text
from .utils import scalable_svg, short_url, whatsapp_share_url


def _my_voters(user):
    return Voter.objects.filter(campaign_id=user.campaign_id, registered_by_id=user.pk)


@module_permission_required("meu_link", "view")
@never_cache
@require_GET
def my_link(request):
    user = request.user
    campaign = request.campaign
    link = registration_url(user.invite_code)
    qr_link = registration_url(user.invite_code, "qr")

    mine = _my_voters(user)
    today_start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    total = mine.count()
    stats = {
        "today": mine.filter(created_at__gte=today_start).count(),
        "week": mine.filter(created_at__gte=today_start - timedelta(days=6)).count(),
        "total": total,
    }
    goal = user.goal or 0
    can_list = can(request.perms, "eleitores", "view")
    recent = list(mine.order_by("-created_at").values("name", "neighborhood", "created_at")[:5]) if can_list else []

    return render(
        request,
        "voters/my_link.html",
        {
            "link": link,
            "short_link": short_url(link),
            "qr_data_url": qr_png_data_url(qr_link, scale=14),
            "qr_filename": f"qrcode-{slugify(campaign.ballot_name) or 'campanha'}.png",
            "share_url": whatsapp_share_url(share_text(campaign, link)),
            "stats": stats,
            "goal": goal,
            "goal_pct": min(100, round(total / goal * 100)) if goal else 0,
            "goal_remaining": max(0, goal - total),
            "recent": recent,
            "can_list": can_list,
            "brand": brand_for(campaign),
        },
    )


@module_permission_required("meu_link", "view")
@require_GET
def my_link_poster(request):
    user = request.user
    campaign = request.campaign
    link = registration_url(user.invite_code)
    # SVG gerado pela biblioteca a partir de uma URL nossa (sem dados do usuário): seguro para marcar como HTML
    svg = mark_safe(scalable_svg(qr_svg(registration_url(user.invite_code, "qr"), scale=10)))  # noqa: S308
    return render(
        request,
        "voters/poster.html",
        {"qr_svg": svg, "short_link": short_url(link), "brand": brand_for(campaign), "campaign": campaign},
    )
