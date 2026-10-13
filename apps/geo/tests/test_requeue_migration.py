"""Migração 0003: ao atualizar, eleitores localizados pela versão antiga voltam à fila para serem localizados de novo."""

import importlib

from django.apps import apps
from django.test import TestCase

from apps.core.constants import Role
from apps.core.tests.test_access import make_campaign, make_user
from apps.geo.models import CepCache
from apps.voters.models import Voter

migration = importlib.import_module("apps.geo.migrations.0003_requeue_geocoding")

WRONG = (-22.90642, -43.18223)  # ponto do BrasilAPI gravado pela versão antiga (Centro do Rio)


def make_voter(campaign, owner, n, **extra):
    data = dict(cep="21660000", street="Avenida Brasil", neighborhood="Guadalupe", city="Rio de Janeiro", state="RJ",
                latitude=WRONG[0], longitude=WRONG[1], geo_status="OK")  # fmt: skip
    data.update(extra)
    return Voter.objects.create(campaign=campaign, registered_by=owner, name=f"Eleitor {n}", phone=f"5521988880{n:03d}", **data)


class RequeueMigrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a, cls.b = make_campaign("alfa"), make_campaign("beta")
        cls.admin_a = make_user(cls.a, "admin@a.com", Role.ADMIN)
        cls.admin_b = make_user(cls.b, "admin@b.com", Role.ADMIN)
        cls.ok = make_voter(cls.a, cls.admin_a, 1)
        cls.approximate = make_voter(cls.a, cls.admin_a, 2, geo_status="APPROXIMATE")
        cls.failed = make_voter(cls.a, cls.admin_a, 3, geo_status="FAILED", latitude=None, longitude=None)
        cls.no_address = make_voter(cls.a, cls.admin_a, 4, cep="", city="", street="", neighborhood="", state="")
        cls.other_campaign = make_voter(cls.b, cls.admin_b, 5)

    def run_migration(self):
        migration.requeue_geocoding(apps, None)
        for voter in (self.ok, self.approximate, self.failed, self.no_address, self.other_campaign):
            voter.refresh_from_db()

    def test_voters_with_an_address_go_back_to_the_queue_keeping_the_old_point_until_the_new_result(self):
        self.run_migration()
        for voter in (self.ok, self.approximate, self.failed, self.other_campaign):
            self.assertEqual(voter.geo_status, "PENDING", voter.name)
        self.assertAlmostEqual(self.ok.latitude, WRONG[0])  # o ponto antigo continua até o worker refazer
        self.assertEqual(self.no_address.geo_status, "OK")  # sem CEP nem cidade não há o que localizar

    def test_legacy_point_and_area_cache_is_dropped_but_cep_addresses_are_kept(self):
        CepCache.objects.create(key="21660000", street="Avenida Brasil", city="Rio de Janeiro", latitude=WRONG[0],
                                longitude=WRONG[1], geo_source="brasilapi")
        CepCache.objects.create(key="A:rj:rio-de-janeiro:guadalupe", latitude=1, longitude=1, geo_source="none")
        CepCache.objects.create(key="P:21660000:guadalupe", latitude=1, longitude=1, geo_source="brasilapi")
        CepCache.objects.create(key="S:rj:rio-de-janeiro:guadalupe:avenida-brasil", geo_source="none")
        self.run_migration()
        self.assertEqual(list(CepCache.objects.values_list("key", flat=True)), ["21660000"])

    def test_is_idempotent_and_has_a_noop_reverse(self):
        self.run_migration()
        self.run_migration()
        self.assertEqual(Voter.objects.filter(geo_status="PENDING").count(), 4)
        reverse = migration.Migration.operations[0].reverse_code
        reverse(apps, None)  # não faz nada e não falha
        self.assertEqual(Voter.objects.filter(geo_status="PENDING").count(), 4)
