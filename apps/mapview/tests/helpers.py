"""Fixtures dos testes do mapa (campanhas, usuários, eleitores e login)."""

from __future__ import annotations

from django.test import Client, override_settings

from apps.accounts.models import User
from apps.campaigns.bootstrap import bootstrap_campaign
from apps.campaigns.models import Campaign
from apps.voters.models import Voter

PASSWORD = "Senha@12345"
BACKEND = "apps.accounts.backends.EmailBackend"

# Hash rápido só nos testes (o PBKDF2 de produção deixaria a suíte lenta)
fast_hashing = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


def make_campaign(slug: str) -> Campaign:
    campaign = Campaign.objects.create(
        slug=slug, candidate_name=slug.title(), ballot_name=slug.title(), office="VEREADOR", election_year=2026
    )
    bootstrap_campaign(campaign)
    return campaign


def make_user(campaign, email: str, role: str, parent=None, name: str | None = None, **extra) -> User:
    return User.objects.create_user(
        email, PASSWORD, name=name or email.split("@")[0].title(), role=role, campaign=campaign, parent=parent, **extra
    )


def make_voter(campaign, registered_by, n: int, **extra) -> Voter:
    return Voter.objects.create(
        campaign=campaign, registered_by=registered_by, name=f"Eleitor Secreto {n}", phone=f"551190000{n:04d}", **extra
    )


def client_for(user) -> Client:
    """Cliente já autenticado (sem passar pelo login, que tem limite de tentativas por IP)."""
    client = Client()
    client.force_login(user, backend=BACKEND)
    return client
