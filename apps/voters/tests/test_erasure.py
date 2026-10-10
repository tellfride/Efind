"""Direito de eliminação (LGPD): excluir o eleitor não deixa telefone/texto em históricos de mensagens."""

from django.test import TestCase

from apps.core.constants import Role
from apps.messaging.models import Broadcast, BroadcastMessage
from apps.voters.models import Voter
from apps.whatsapp.models import InboundMessage

from .helpers import PASSWORD, make_campaign, make_user, next_phone


class VoterErasureTests(TestCase):
    def test_delete_anonymizes_message_history(self):
        campaign = make_campaign("lgpd")
        admin = make_user(campaign, "admin@lgpd.com", Role.ADMIN)
        voter = Voter.objects.create(campaign=campaign, registered_by=admin, name="Maria", phone=next_phone())
        broadcast = Broadcast.objects.create(campaign=campaign, name="Aviso", created_by=admin, filters={})
        sent = BroadcastMessage.objects.create(
            broadcast=broadcast, campaign=campaign, voter=voter, phone=voter.phone,
            rendered_body="Olá, Maria!", status="SENT", error="falha com o telefone",
        )  # fmt: skip
        inbound = InboundMessage.objects.create(campaign=campaign, from_phone=voter.phone, body="SAIR", voter=voter)

        self.assertTrue(self.client.login(username="admin@lgpd.com", password=PASSWORD))
        response = self.client.post(f"/painel/eleitores/{voter.pk}/excluir/")

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Voter.objects.filter(pk=voter.pk).exists())
        sent.refresh_from_db()
        inbound.refresh_from_db()
        # o histórico/contagem permanece, sem dados pessoais
        self.assertEqual((sent.phone, sent.rendered_body, sent.error, sent.status), ("", "", "", "SENT"))
        self.assertEqual((inbound.from_phone, inbound.body), ("", ""))
