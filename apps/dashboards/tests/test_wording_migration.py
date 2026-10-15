"""Migração 0002: a descrição padrão antiga do dashboard Territorial passa a falar em apoiadores."""

import importlib

from django.apps import apps
from django.test import TestCase

from apps.dashboards.models import Dashboard

from .helpers import make_campaign

migration = importlib.import_module("apps.dashboards.migrations.0002_apoiadores_wording")


class WordingMigrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.campaign = make_campaign("texto")

    def test_old_default_description_is_replaced_and_edited_ones_are_kept(self):
        territorial = Dashboard.objects.get(campaign=self.campaign, name="Territorial")
        Dashboard.objects.filter(pk=territorial.pk).update(description=migration.OLD)
        edited = Dashboard.objects.create(
            campaign=self.campaign, name="Meu painel", description="Onde estão os eleitores da zona norte"
        )
        migration.rename(apps, None)
        territorial.refresh_from_db()
        edited.refresh_from_db()
        self.assertEqual(territorial.description, migration.NEW)
        self.assertEqual(edited.description, "Onde estão os eleitores da zona norte")  # texto da equipe: intocado

    def test_new_campaigns_already_get_the_new_text(self):
        territorial = Dashboard.objects.get(campaign=self.campaign, name="Territorial")
        self.assertEqual(territorial.description, migration.NEW)
