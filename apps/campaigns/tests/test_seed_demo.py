"""seed_demo cria contas com senha conhecida: só roda em desenvolvimento (ou com --force / ALLOW_SEED_DEMO=1)."""

import os
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.accounts.models import User
from apps.campaigns.models import Campaign
from apps.voters.models import Voter

ENV = {"SEED_SUPERADMIN_PASSWORD": "Teste@12345", "SEED_SUPERADMIN_EMAIL": "seed-super@efind.test"}


def run(**options):
    call_command("seed_demo", stdout=StringIO(), **options)


class SeedDemoGuardTests(TestCase):
    def test_refuses_to_run_with_debug_off(self):
        # o runner de testes mantém DEBUG=False, como em produção
        with mock.patch.dict(os.environ, ENV), self.assertRaisesMessage(CommandError, "só deve rodar em desenvolvimento"):
            run(voters=3)
        self.assertFalse(Campaign.objects.filter(slug="demo").exists())
        self.assertFalse(User.objects.filter(email=ENV["SEED_SUPERADMIN_EMAIL"]).exists())

    def test_force_flag_runs_and_is_idempotent(self):
        with mock.patch.dict(os.environ, ENV):
            run(force=True, voters=5)
            run(force=True, voters=5)  # idempotente: não duplica
        self.assertEqual(Campaign.objects.filter(slug="demo").count(), 1)
        self.assertEqual(Voter.objects.filter(campaign__slug="demo").count(), 5)
        self.assertTrue(User.objects.filter(email="admin@demo.efind.com.br", role="ADMIN").exists())
        self.assertTrue(User.objects.filter(email=ENV["SEED_SUPERADMIN_EMAIL"], role="SUPER_ADMIN").exists())

    def test_environment_override(self):
        with mock.patch.dict(os.environ, {**ENV, "ALLOW_SEED_DEMO": "1"}):
            run(voters=2)
        self.assertTrue(Campaign.objects.filter(slug="demo").exists())

    def test_requires_a_super_admin_password(self):
        with mock.patch.dict(os.environ, {"SEED_SUPERADMIN_PASSWORD": ""}), self.assertRaisesMessage(CommandError, "SEED_SUPERADMIN_PASSWORD"):
            run(force=True, voters=2)
