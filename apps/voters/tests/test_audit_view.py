"""LGPD: quem abriu a ficha de um eleitor fica registrado (só o id, sem dados pessoais)."""

from django.test import TestCase

from apps.auditlog.actions import action_label
from apps.auditlog.models import AuditLog
from apps.core.constants import Role
from apps.voters.models import Voter

from .helpers import PASSWORD, make_campaign, make_user, next_phone


class VoterViewAuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.campaign = make_campaign("auditv")
        cls.admin = make_user(cls.campaign, "adm@auditv.com", Role.ADMIN)
        cls.cabo = make_user(cls.campaign, "cabo@auditv.com", Role.CABO, parent=cls.admin)
        cls.other_cabo = make_user(cls.campaign, "outro@auditv.com", Role.CABO, parent=cls.admin)
        cls.voter = Voter.objects.create(campaign=cls.campaign, registered_by=cls.cabo, name="Fulana de Tal", phone=next_phone())
        cls.other_voter = Voter.objects.create(campaign=cls.campaign, registered_by=cls.other_cabo, name="Beltrana", phone=next_phone())

    def test_opening_a_voter_is_audited_without_personal_data(self):
        self.assertTrue(self.client.login(username="cabo@auditv.com", password=PASSWORD))
        self.assertEqual(self.client.get(f"/painel/eleitores/{self.voter.pk}/").status_code, 200)
        entry = AuditLog.objects.get(action="voter.view")
        self.assertEqual(entry.entity, "Voter")
        self.assertEqual(entry.entity_id, str(self.voter.pk))
        self.assertEqual(entry.user, self.cabo)
        self.assertEqual(entry.campaign, self.campaign)
        self.assertIsNone(entry.details)
        self.assertNotIn("Fulana", repr(entry.__dict__))

    def test_out_of_scope_voter_is_404_and_not_audited(self):
        self.assertTrue(self.client.login(username="cabo@auditv.com", password=PASSWORD))
        self.assertEqual(self.client.get(f"/painel/eleitores/{self.other_voter.pk}/").status_code, 404)
        self.assertFalse(AuditLog.objects.filter(action="voter.view").exists())

    def test_action_has_a_portuguese_label(self):
        self.assertEqual(action_label("voter.view"), "Ficha do eleitor consultada")
