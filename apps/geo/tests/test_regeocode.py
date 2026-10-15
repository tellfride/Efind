"""Comando regeocode e botão "Relocalizar todos": refazem a localização sem vazar para outras campanhas."""

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.core.constants import Role
from apps.core.tests.test_access import PASSWORD, make_campaign, make_user
from apps.geo.geocode import GeoPoint
from apps.geo.models import CepCache
from apps.voters.models import Voter

WRONG = (-22.90642, -43.18223)  # Centro do Rio
RIGHT = GeoPoint(-22.8427, -43.3730, "OK", "nominatim-rua")  # Guadalupe


def make_voter(campaign, owner, n, **extra):
    data = dict(cep="21670000", street="Avenida Brasil", neighborhood="Guadalupe", city="Rio de Janeiro", state="RJ",
                latitude=WRONG[0], longitude=WRONG[1], geo_status="OK")  # fmt: skip
    data.update(extra)
    return Voter.objects.create(campaign=campaign, registered_by=owner, name=f"Apoiador {n}", phone=f"5521999990{n:03d}", **data)


class RegeocodeCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a, cls.b = make_campaign("alfa"), make_campaign("beta")
        cls.admin_a = make_user(cls.a, "admin@a.com", Role.ADMIN)
        cls.admin_b = make_user(cls.b, "admin@b.com", Role.ADMIN)
        cls.v1, cls.v2 = make_voter(cls.a, cls.admin_a, 1), make_voter(cls.a, cls.admin_a, 2)
        cls.no_address = make_voter(cls.a, cls.admin_a, 3, cep="", city="", street="", neighborhood="", state="")
        cls.other = make_voter(cls.b, cls.admin_b, 4)

    def run_command(self, **options):
        out = StringIO()
        with mock.patch("apps.geo.geocode.geocode_address", return_value=RIGHT):
            call_command("regeocode", stdout=out, **options)
        return out.getvalue()

    def test_all_flag_fixes_wrong_coordinates_of_the_chosen_campaign_only(self):
        output = self.run_command(campaign="alfa", all=True)
        for voter in (self.v1, self.v2):
            voter.refresh_from_db()
            self.assertAlmostEqual(voter.latitude, -22.8427, places=3)
            self.assertEqual(voter.geo_status, "OK")
        self.other.refresh_from_db()
        self.assertAlmostEqual(self.other.latitude, WRONG[0])  # outra campanha intacta
        self.no_address.refresh_from_db()
        self.assertAlmostEqual(self.no_address.latitude, WRONG[0])  # sem endereço: não há o que localizar
        self.assertIn("Concluído: 2 localizados na rua", output)

    def test_without_all_only_pending_and_failed_are_processed(self):
        Voter.objects.filter(pk=self.v2.pk).update(geo_status="FAILED")
        self.run_command(campaign="alfa")
        self.v1.refresh_from_db()
        self.v2.refresh_from_db()
        self.assertAlmostEqual(self.v1.latitude, WRONG[0])  # já estava OK: não mexe
        self.assertAlmostEqual(self.v2.latitude, -22.8427, places=3)  # falhou antes: refeito

    def test_all_campaigns_when_no_slug_is_given(self):
        self.run_command(all=True)
        self.other.refresh_from_db()
        self.assertAlmostEqual(self.other.latitude, -22.8427, places=3)

    def test_unknown_campaign_is_an_error(self):
        with self.assertRaisesMessage(CommandError, "não encontrada"):
            call_command("regeocode", campaign="nao-existe", stdout=StringIO())

    def test_limit(self):
        self.run_command(campaign="alfa", all=True, limit=1)
        self.assertEqual(Voter.objects.filter(campaign=self.a, geo_status="PENDING").count(), 1)

    def test_purge_cache_removes_points_and_areas_but_keeps_cep_addresses(self):
        CepCache.objects.create(key="P:21670000:guadalupe", latitude=1, longitude=1, geo_source="brasilapi")
        CepCache.objects.create(key="A:rj:rio-de-janeiro:guadalupe", latitude=1, longitude=1, geo_source="nominatim-bairro")
        CepCache.objects.create(key="21670000", street="Avenida Brasil", city="Rio de Janeiro")
        self.run_command(campaign="alfa", all=True, purge_cache=True)
        self.assertEqual(list(CepCache.objects.values_list("key", flat=True)), ["21670000"])

    def test_nothing_to_do(self):
        Voter.objects.all().update(geo_status="OK")
        self.assertIn("Nada a processar", self.run_command(campaign="alfa"))


class RequeueButtonTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a, cls.b = make_campaign("alfa"), make_campaign("beta")
        cls.admin = make_user(cls.a, "admin@a.com", Role.ADMIN)
        cls.coord = make_user(cls.a, "coord@a.com", Role.COORDENADOR, parent=cls.admin)
        cls.admin_b = make_user(cls.b, "admin@b.com", Role.ADMIN)
        cls.mine = make_voter(cls.a, cls.admin, 1)
        cls.no_address = make_voter(cls.a, cls.admin, 2, cep="", city="")
        cls.other = make_voter(cls.b, cls.admin_b, 3)

    def post(self, email):
        self.client.logout()
        self.assertTrue(self.client.login(username=email, password=PASSWORD))
        return self.client.post("/painel/mapa/relocalizar-todos/")

    def test_admin_requeues_only_own_campaign_voters_with_address(self):
        response = self.post("admin@a.com")
        self.assertEqual(response.status_code, 302)
        statuses = {v.pk: v.geo_status for v in Voter.objects.all()}
        self.assertEqual(statuses[self.mine.pk], "PENDING")
        self.assertEqual(statuses[self.no_address.pk], "OK")
        self.assertEqual(statuses[self.other.pk], "OK")  # outra campanha intacta
        self.assertAlmostEqual(Voter.objects.get(pk=self.mine.pk).latitude, WRONG[0])  # mantém o ponto até o novo resultado

    def test_only_admin_can_use_it(self):
        self.assertEqual(self.post("coord@a.com").status_code, 403)
        self.assertEqual(Voter.objects.get(pk=self.mine.pk).geo_status, "OK")

    def test_requires_post_and_login(self):
        self.client.logout()
        self.assertEqual(self.client.post("/painel/mapa/relocalizar-todos/").status_code, 302)  # sem sessão → login
        self.assertTrue(self.client.login(username="admin@a.com", password=PASSWORD))
        self.assertEqual(self.client.get("/painel/mapa/relocalizar-todos/").status_code, 405)

    def test_button_is_shown_to_the_admin_on_the_map(self):
        self.assertTrue(self.client.login(username="admin@a.com", password=PASSWORD))
        page = self.client.get("/painel/mapa/")
        self.assertContains(page, "Relocalizar todos os apoiadores")
        self.assertContains(page, "/painel/mapa/relocalizar-todos/")
