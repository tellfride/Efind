"""Fixtures compartilhadas pelos testes do módulo de WhatsApp (sem rede, SQLite em memória)."""

from __future__ import annotations

import base64

from django.test import override_settings

from apps.accounts.models import RolePermission, User
from apps.campaigns.bootstrap import bootstrap_campaign
from apps.campaigns.models import Campaign
from apps.core.constants import ConnectionStatus, Role
from apps.core.crypto import encrypt_json, random_token
from apps.voters.models import Voter
from apps.whatsapp.models import WhatsAppConnection

PASSWORD = "Senha@12345"
TEST_KEY = base64.b64encode(b"k" * 32).decode()

# Segredos únicos: os testes verificam que NUNCA aparecem em HTML, JSON ou auditoria
META_TOKEN = "EAAGsegredoMETAtoken1234567890XYZ"
META_APP_SECRET = "appsecretMETA0123456789abcdef"
TWILIO_SID = "AC" + "a1" * 16
TWILIO_AUTH = "twilioauthtoken0123456789abcd"
D360_KEY = "d360apikey-segredo-0123456789"

crypto_settings = override_settings(ENCRYPTION_KEY=TEST_KEY, APP_URL="https://efind.test")


def make_campaign(slug: str) -> Campaign:
    campaign = Campaign.objects.create(
        slug=slug, candidate_name=slug.title(), ballot_name=slug.title(), office="VEREADOR", election_year=2026
    )
    bootstrap_campaign(campaign)
    return campaign


def make_user(campaign, email: str, role: str, parent=None, **extra) -> User:
    return User.objects.create_user(
        email, PASSWORD, name=email.split("@")[0], role=role, campaign=campaign, parent=parent, **extra
    )


def make_super_admin(email: str = "super@efind.test") -> User:
    return User.objects.create_user(email, PASSWORD, name="Super", role=Role.SUPER_ADMIN)


def grant(campaign, role: str, module: str, *, view=False, edit=False) -> None:
    """Ajusta a linha da matriz de permissões do papel (ex.: coordenador só com leitura em whatsapp)."""
    RolePermission.objects.update_or_create(
        campaign=campaign, role=role, module=module, defaults={"can_view": view, "can_edit": edit}
    )


def make_voter(campaign, registered_by, n: int, **extra) -> Voter:
    return Voter.objects.create(campaign=campaign, registered_by=registered_by, name=f"Eleitor {n}", phone=f"5511900000{n:03d}", **extra)


META_CREDENTIALS = {
    "phone_number_id": "123456789012345",
    "business_account_id": "109876543210987",
    "access_token": META_TOKEN,
    "app_secret": META_APP_SECRET,
    "api_version": "v21.0",
}
TWILIO_CREDENTIALS = {"account_sid": TWILIO_SID, "auth_token": TWILIO_AUTH, "from_number": "+5511999990000"}


def make_connection(
    campaign,
    *,
    provider: str = "META_CLOUD",
    name: str = "Conexão teste",
    status: str = ConnectionStatus.CONNECTED,
    credentials: dict | None = None,
    is_default: bool = False,
    **extra,
) -> WhatsAppConnection:
    if credentials is None:
        credentials = {"META_CLOUD": META_CREDENTIALS, "TWILIO": TWILIO_CREDENTIALS, "DIALOG360": {"api_key": D360_KEY}}.get(
            provider, {"failure_rate": "0"}
        )
    return WhatsAppConnection.objects.create(
        campaign=campaign,
        name=name,
        provider=provider,
        status=status,
        credentials=encrypt_json(credentials),
        webhook_token=random_token(),
        is_default=is_default,
        **extra,
    )
