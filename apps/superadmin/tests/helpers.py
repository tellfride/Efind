"""Fixtures compartilhadas dos testes do super admin (sem rede; SQLite em memória)."""

from __future__ import annotations

from django.test import Client, RequestFactory, override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.campaigns.bootstrap import bootstrap_campaign
from apps.campaigns.models import Campaign
from apps.core.constants import Role
from apps.voters.models import Voter

PASSWORD = "Senha@12345"

# PBKDF2 é lento demais para dezenas de usuários por teste
fast_hasher = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


def make_campaign(slug="alfa", ballot_name=None, **extra) -> Campaign:
    data = {
        "slug": slug,
        "candidate_name": slug.title(),
        "ballot_name": ballot_name or slug.title(),
        "office": "VEREADOR",
        "election_year": 2026,
    }
    data.update(extra)
    campaign = Campaign.objects.create(**data)
    bootstrap_campaign(campaign)
    return campaign


def make_user(campaign, email, role, parent=None, **extra) -> User:
    return User.objects.create_user(
        email, PASSWORD, name=extra.pop("name", email.split("@")[0].title() + " Teste"), role=role, campaign=campaign, parent=parent, **extra
    )


def make_super(email="super@efind.test", **extra) -> User:
    return make_user(None, email, Role.SUPER_ADMIN, **extra)


def make_voter(campaign, registered_by, n, **extra) -> Voter:
    return Voter.objects.create(
        campaign=campaign, registered_by=registered_by, name=f"Eleitora Sigilosa {n}", phone=f"5511900000{n:03d}", **extra
    )


def client_for(user) -> Client:
    client = Client()
    client.force_login(user)
    return client


def request_for(user):
    """Request fictícia (usada pelos serviços para auditar com usuário e IP)."""
    request = RequestFactory().post("/super/")
    request.user = user
    return request


def campaign_post_data(**overrides) -> dict:
    """POST válido de /super/campanhas/nova/ (campos do administrador usam o prefixo `admin-`)."""
    data = {
        "candidate_name": "João da Silva",
        "ballot_name": "João Silva",
        "ballot_number": "12345",
        "party": "PSD",
        "office": "VEREADOR",
        "city": "Campinas",
        "state": "SP",
        "election_year": str(timezone.localdate().year),
        "primary_color": "#112233",
        "voter_goal": "5000",
        "admin-name": "Maria Administradora",
        "admin-email": "  Maria.Admin@Exemplo.com ",
        "admin-phone": "(19) 98765-4321",
        "admin-password": "",
    }
    data.update(overrides)
    return data


def campaign_edit_data(campaign: Campaign, **overrides) -> dict:
    """POST válido de edição (campos do próprio CampaignForm, sem prefixo)."""
    data = {
        "candidate_name": campaign.candidate_name,
        "ballot_name": campaign.ballot_name,
        "ballot_number": campaign.ballot_number,
        "party": campaign.party,
        "office": campaign.office,
        "city": campaign.city,
        "state": campaign.state,
        "election_year": str(campaign.election_year),
        "primary_color": campaign.primary_color,
        "voter_goal": str(campaign.voter_goal or ""),
    }
    data.update(overrides)
    return data
