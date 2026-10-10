"""Fixtures dos testes de mensagens: campanhas, equipe, eleitores, conexões, modelos e disparos em memória
(SQLite), com o provedor de WhatsApp sempre simulado (nenhum teste acessa a rede)."""

from __future__ import annotations

from datetime import timedelta
from itertools import count
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.campaigns.bootstrap import bootstrap_campaign
from apps.campaigns.models import Campaign
from apps.core.constants import BroadcastStatus, ConnectionStatus, MessageStatus, Role
from apps.messaging.models import Broadcast, BroadcastMessage, MessageTemplate
from apps.voters.models import Voter
from apps.whatsapp.models import WhatsAppConnection
from apps.whatsapp.types import SendResult

PASSWORD = "Senha@12345"
_seq = count(1)

BODY = "Olá, {{primeiro_nome}}! Aqui é {{candidato}}. Responda SAIR para não receber mais mensagens."


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


def make_voter(campaign, registered_by, *, consent=True, **extra):
    """Eleitor; por padrão já com consentimento de WhatsApp (apto a receber disparos)."""
    n = next(_seq)
    data = dict(name=f"Eleitor {n} Sobrenome", phone=f"55119{n:08d}")
    if consent:
        data.update(whatsapp_opt_in=True, consent_at=timezone.now())
    data.update(extra)
    return Voter.objects.create(campaign=campaign, registered_by=registered_by, **data)


def make_connection(campaign, *, provider="SANDBOX", status=ConnectionStatus.CONNECTED, rate=60, default=True, **extra):
    n = next(_seq)
    return WhatsAppConnection.objects.create(
        campaign=campaign,
        name=extra.pop("name", f"Conexão {n}"),
        provider=provider,
        status=status,
        credentials="x",
        webhook_token=f"token-{n}-{campaign.pk}",
        is_default=default,
        rate_per_minute=rate,
        **extra,
    )


def make_template(campaign, created_by=None, *, body=BODY, **extra):
    n = next(_seq)
    data = dict(name=f"Modelo {n}", category="INFORMATIVO", type="TEXT")
    data.update(extra)
    return MessageTemplate.objects.create(campaign=campaign, created_by=created_by, body=body, **data)


def make_broadcast(campaign, created_by, template, connection, *, status=BroadcastStatus.SCHEDULED, **extra):
    data = dict(name="Disparo de teste", filters={}, rate_per_minute=20, scheduled_at=timezone.now() - timedelta(minutes=1))
    data.update(extra)
    return Broadcast.objects.create(
        campaign=campaign, created_by=created_by, template=template, connection=connection, status=status, **data
    )


def make_message(broadcast, voter, *, status=MessageStatus.PENDING, **extra):
    return BroadcastMessage.objects.create(
        broadcast=broadcast,
        campaign_id=broadcast.campaign_id,
        voter=voter,
        phone=voter.phone,
        rendered_body=extra.pop("rendered_body", "Olá!"),
        status=status,
        **extra,
    )


class FakeProvider:
    """Provedor de teste: devolve os resultados programados (ou sucesso) e guarda o que foi enviado."""

    key = "FAKE"

    def __init__(self, results=None):
        self.results = list(results or [])
        self.sent = []

    def send(self, message):
        self.sent.append(message)
        if self.results:
            result = self.results.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result
        return SendResult(ok=True, provider_message_id=f"wamid.{len(self.sent)}")

    def test_connection(self):  # pragma: no cover — contrato do protocolo
        raise NotImplementedError


@override_settings(
    ROOT_URLCONF="apps.messaging.tests.urls",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],  # testes mais rápidos
)
class MessagingTestCase(TestCase):
    """Duas campanhas com ADMIN → COORDENADOR → CABO. O provedor real nunca é usado; a geocodificação é simulada."""

    def setUp(self):
        cache.clear()
        patcher = mock.patch("apps.geo.geocode.process_pending_geocoding", return_value=0)
        self.geocode = patcher.start()
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
        cls.superuser = User.objects.create_superuser("super@x.com", PASSWORD)

    def login(self, user):
        self.client.force_login(user)
        return self.client

    def grant(self, user, module, **actions):
        """Concede/retira ações de um módulo para um usuário (exceção por usuário)."""
        from apps.accounts.models import UserPermission

        fields = {f"can_{name}": value for name, value in actions.items()}
        UserPermission.objects.update_or_create(user=user, module=module, defaults=fields)
