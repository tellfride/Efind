"""Fixtures dos testes de eleitores: campanhas, usuários e eleitores em memória (SQLite), sem rede."""

from itertools import count
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.accounts.models import User
from apps.campaigns.bootstrap import bootstrap_campaign
from apps.campaigns.models import Campaign
from apps.core.constants import Role
from apps.voters.models import Voter

PASSWORD = "Senha@12345"
_phone_seq = count(1)


def make_campaign(slug, **extra):
    data = dict(
        slug=slug,
        candidate_name=f"Candidato {slug.title()}",
        ballot_name=slug.title(),
        ballot_number="12345",
        party="PXX",
        office="VEREADOR",
        election_year=2026,
    )
    data.update(extra)
    campaign = Campaign.objects.create(**data)
    bootstrap_campaign(campaign)
    return campaign


def make_user(campaign, email, role, parent=None, **extra):
    name = extra.pop("name", email.split("@")[0].title())
    return User.objects.create_user(email, PASSWORD, name=name, role=role, campaign=campaign, parent=parent, **extra)


def next_phone():
    return f"55119{next(_phone_seq):08d}"


def make_voter(campaign, registered_by, **extra):
    n = next(_phone_seq)
    data = dict(name=f"Eleitor {n}", phone=f"55119{n:08d}")
    data.update(extra)
    return Voter.objects.create(campaign=campaign, registered_by=registered_by, **data)


@override_settings(ROOT_URLCONF="apps.voters.tests.urls")
class VoterTestCase(TestCase):
    """Cria duas campanhas com a hierarquia ADMIN → COORDENADOR → CABO e limpa o cache (limite de taxa)."""

    def setUp(self):
        cache.clear()
        patcher = mock.patch("apps.voters.views_public.geocode_voter_in_background")
        self.geocode_public = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch("apps.voters.views_panel.geocode_voter_in_background")
        self.geocode_panel = patcher.start()
        self.addCleanup(patcher.stop)

    @classmethod
    def setUpTestData(cls):
        cls.a = make_campaign("alfa")
        cls.b = make_campaign("beta")
        cls.admin = make_user(cls.a, "admin@a.com", Role.ADMIN, name="Ana Admin")
        cls.coord1 = make_user(cls.a, "coord1@a.com", Role.COORDENADOR, parent=cls.admin, name="Carlos Coord")
        cls.coord2 = make_user(cls.a, "coord2@a.com", Role.COORDENADOR, parent=cls.admin, name="Clara Coord")
        cls.cabo1 = make_user(cls.a, "cabo1@a.com", Role.CABO, parent=cls.coord1, name="Caio Cabo")
        cls.cabo2 = make_user(cls.a, "cabo2@a.com", Role.CABO, parent=cls.coord2, name="Cida Cabo")
        cls.admin_b = make_user(cls.b, "admin@b.com", Role.ADMIN, name="Beto Admin")

    def login(self, user):
        self.client.force_login(user)
        return self.client
