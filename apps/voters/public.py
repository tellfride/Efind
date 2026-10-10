"""Dados públicos do link de cadastro (/c/<code>/): expõe só o necessário para a página (identidade visual da
campanha e o primeiro nome de quem indicou). Nada de dados de eleitores ou da equipe."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.accounts.models import User
from apps.core.constants import DEFAULT_CONSENT_TEXT, CampaignStatus, Office, Role, label_of
from apps.core.qr import registration_url
from apps.core.template_vars import render_template
from apps.core.utils import first_name

from .utils import (
    brand_style,
    is_valid_invite_code,
    readable_text_color,
    safe_hex_color,
    safe_logo_url,
    whatsapp_share_url,
)


@dataclass(frozen=True)
class PublicBrand:
    color: str  # #rrggbb validado
    text_color: str  # cor legível sobre `color`
    style: str  # variáveis CSS brand-* (atributo style do contêiner)
    logo_url: str  # vazio se ausente/inseguro
    office_label: str


def brand_for(campaign) -> PublicBrand:
    """Identidade visual da campanha (cor validada, logo segura, rótulo do cargo)."""
    color = safe_hex_color(campaign.primary_color)
    return PublicBrand(
        color=color,
        text_color=readable_text_color(color),
        style=brand_style(color),
        logo_url=safe_logo_url(campaign.logo_url),
        office_label=label_of(Office, campaign.office),
    )


def share_text(campaign, url: str) -> str:
    """Texto de convite para compartilhar o link de cadastro (o mesmo link: o membro mantém o crédito)."""
    number = f" ({campaign.ballot_number})" if campaign.ballot_number else ""
    return f"Faça parte da campanha de {campaign.ballot_name}{number}! Cadastre-se aqui: {url}"


@dataclass(frozen=True)
class PublicRegistration:
    code: str  # código canônico do usuário
    owner: Any  # User dono do link (nunca exposto além do primeiro nome)
    owner_first_name: str
    campaign: Any
    brand: PublicBrand

    @property
    def url(self) -> str:
        return registration_url(self.code)

    @property
    def consent_text(self) -> str:
        return render_template(self.campaign.consent_text or DEFAULT_CONSENT_TEXT, {"candidato": self.campaign.ballot_name})

    @property
    def share_url(self) -> str:
        return whatsapp_share_url(share_text(self.campaign, self.url))


def get_public_registration(code: str | None) -> PublicRegistration | None:
    """Usuário ATIVO dono do código + campanha ATIVA; None caso contrário (link inválido ou desativado)."""
    if not is_valid_invite_code(code):
        return None
    user = User.objects.select_related("campaign").filter(invite_code=code).first()
    if (
        user is None
        or not user.is_active
        or user.role == Role.SUPER_ADMIN
        or user.campaign is None
        or user.campaign.status != CampaignStatus.ACTIVE
    ):
        return None
    campaign = user.campaign
    return PublicRegistration(
        code=user.invite_code,
        owner=user,
        owner_first_name=first_name(user.name),
        campaign=campaign,
        brand=brand_for(campaign),
    )
