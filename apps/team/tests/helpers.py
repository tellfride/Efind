"""Fixtures compartilhadas pelos testes da equipe (criadas inline, sem rede)."""

from django.test import Client, override_settings

from apps.accounts.models import User
from apps.campaigns.bootstrap import bootstrap_campaign
from apps.campaigns.models import Campaign
from apps.voters.models import Voter

PASSWORD = "Senha@12345"

# Hash rápido só nos testes (o PBKDF2 real deixaria a suíte lenta)
fast_hashers = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


def make_campaign(slug="alfa"):
    campaign = Campaign.objects.create(
        slug=slug, candidate_name=slug.title(), ballot_name=slug.title(), office="VEREADOR", election_year=2026
    )
    bootstrap_campaign(campaign)
    return campaign


def make_user(campaign, email, role, parent=None, **extra):
    extra.setdefault("name", email.split("@")[0].title())
    return User.objects.create_user(email, PASSWORD, role=role, campaign=campaign, parent=parent, **extra)


def make_voter(campaign, registered_by, n, **extra):
    return Voter.objects.create(
        campaign=campaign, registered_by=registered_by, name=f"Apoiador {n}", phone=f"5511900000{n:03d}", **extra
    )


def login(user) -> Client:
    client = Client()
    client.force_login(user)
    return client
