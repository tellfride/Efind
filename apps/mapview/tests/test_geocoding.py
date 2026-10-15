"""Ação do ADMIN "Localizar pendentes agora": só ADMIN, só a própria campanha, sem rede (geocode_voter é simulado)."""

from unittest import mock

from django.contrib.messages import get_messages
from django.core.cache import cache
from django.test import Client, SimpleTestCase, TestCase

from apps.auditlog.models import AuditLog
from apps.core.constants import GeoStatus, Role
from apps.mapview.geocoding import (
    DEFAULT_LIMIT,
    GeocodeRunResult,
    geocode_run_message,
    run_campaign_geocoding,
)
from apps.voters.models import Voter

from .helpers import client_for, fast_hashing, make_campaign, make_user, make_voter

URL = "/painel/mapa/localizar-pendentes/"
MAP = "/painel/mapa/"
FAKE_POINT = (-22.9, -47.06)


def fake_geocode(voter_id):
    """Simula apps.geo.geocode.geocode_voter sem rede: apoiadores com CEP 00000-000 falham; os demais são localizados."""
    voter = Voter.objects.get(pk=voter_id)
    if voter.cep == "00000000":
        Voter.objects.filter(pk=voter_id).update(geo_status=GeoStatus.FAILED)
    else:
        Voter.objects.filter(pk=voter_id).update(latitude=FAKE_POINT[0], longitude=FAKE_POINT[1], geo_status=GeoStatus.OK)


def patched():
    return mock.patch("apps.mapview.geocoding.geocode_voter", side_effect=fake_geocode)


@fast_hashing
class GeocodeBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = make_campaign("alfa")
        cls.b = make_campaign("beta")
        cls.admin = make_user(cls.a, "admin@a.com", Role.ADMIN)
        cls.coord = make_user(cls.a, "coord@a.com", Role.COORDENADOR, parent=cls.admin)
        cls.cabo = make_user(cls.a, "cabo@a.com", Role.CABO, parent=cls.coord)
        cls.admin_b = make_user(cls.b, "admin@b.com", Role.ADMIN)

    def setUp(self):
        cache.clear()

    def messages(self, response):
        return [(m.level_tag, str(m)) for m in get_messages(response.wsgi_request)]


class AccessTests(GeocodeBase):
    def test_anonymous_is_redirected_to_login(self):
        response = Client().post(URL)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/login/"))

    def test_only_admin_can_run(self):
        pending = make_voter(self.a, self.cabo, 1, geo_status=GeoStatus.PENDING)
        for user in (self.coord, self.cabo):
            with patched() as geocode:
                response = client_for(user).post(URL)
            self.assertEqual(response.status_code, 403, user.role)
            geocode.assert_not_called()
        pending.refresh_from_db()
        self.assertEqual(pending.geo_status, GeoStatus.PENDING)

    def test_super_admin_cannot_run(self):
        from apps.accounts.models import User

        from .helpers import PASSWORD

        superuser = User.objects.create_superuser("super@x.com", PASSWORD)
        with patched() as geocode:
            response = client_for(superuser).post(URL)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/super/")
        geocode.assert_not_called()

    def test_get_is_not_allowed(self):
        with patched() as geocode:
            self.assertEqual(client_for(self.admin).get(URL).status_code, 405)
        geocode.assert_not_called()

    def test_csrf_is_enforced(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin, backend="apps.accounts.backends.EmailBackend")
        with patched() as geocode:
            self.assertEqual(client.post(URL).status_code, 403)
        geocode.assert_not_called()


class RunTests(GeocodeBase):
    def test_locates_pending_voters_and_reports(self):
        voters = [make_voter(self.a, self.cabo, i, geo_status=GeoStatus.PENDING, cep="13010000") for i in range(1, 4)]
        with patched() as geocode:
            response = client_for(self.admin).post(URL)
        self.assertRedirects(response, MAP, fetch_redirect_response=False)
        self.assertEqual(geocode.call_count, 3)
        for voter in voters:
            voter.refresh_from_db()
            self.assertEqual(voter.geo_status, GeoStatus.OK)
            self.assertEqual(voter.latitude, FAKE_POINT[0])
        self.assertEqual(self.messages(response), [("success", "3 apoiadores localizados.")])

    def test_failed_voters_return_to_queue_and_are_retried(self):
        failed = make_voter(self.a, self.cabo, 1, geo_status=GeoStatus.FAILED, cep="13010000")
        with patched():
            response = client_for(self.admin).post(URL)
        failed.refresh_from_db()
        self.assertEqual(failed.geo_status, GeoStatus.OK)
        self.assertEqual(self.messages(response), [("success", "1 apoiador localizado.")])

    def test_still_failing_voters_are_reported(self):
        make_voter(self.a, self.cabo, 1, geo_status=GeoStatus.PENDING, cep="00000000")
        make_voter(self.a, self.cabo, 2, geo_status=GeoStatus.PENDING, cep="13010000")
        with patched():
            response = client_for(self.admin).post(URL)
        ((level, text),) = self.messages(response)
        self.assertEqual(level, "success")
        self.assertIn("1 apoiador localizado", text)
        self.assertIn("1 endereço não encontrado", text)

    def test_nothing_to_do(self):
        make_voter(self.a, self.cabo, 1, geo_status=GeoStatus.OK, latitude=-22.0, longitude=-47.0)
        with patched() as geocode:
            response = client_for(self.admin).post(URL)
        geocode.assert_not_called()
        self.assertEqual(self.messages(response), [("info", "Não há apoiadores pendentes de localização.")])

    def test_processes_at_most_fifteen_and_keeps_the_rest_queued(self):
        for i in range(1, 21):
            make_voter(self.a, self.cabo, i, geo_status=GeoStatus.PENDING, cep="13010000")
        with patched() as geocode:
            response = client_for(self.admin).post(URL)
        self.assertEqual(DEFAULT_LIMIT, 15)
        self.assertEqual(geocode.call_count, 15)
        self.assertEqual(Voter.objects.filter(campaign=self.a, geo_status=GeoStatus.OK).count(), 15)
        self.assertEqual(Voter.objects.filter(campaign=self.a, geo_status=GeoStatus.PENDING).count(), 5)
        ((_, text),) = self.messages(response)
        self.assertIn("5 apoiadores continuam na fila", text)

    def test_never_touches_another_campaign(self):
        mine = make_voter(self.a, self.cabo, 1, geo_status=GeoStatus.PENDING, cep="13010000")
        theirs_pending = make_voter(self.b, self.admin_b, 2, geo_status=GeoStatus.PENDING, cep="13010000")
        theirs_failed = make_voter(self.b, self.admin_b, 3, geo_status=GeoStatus.FAILED, cep="13010000")
        with patched() as geocode:
            client_for(self.admin).post(URL)
        geocode.assert_called_once_with(mine.pk)
        theirs_pending.refresh_from_db()
        theirs_failed.refresh_from_db()
        self.assertEqual(theirs_pending.geo_status, GeoStatus.PENDING)
        self.assertEqual(theirs_failed.geo_status, GeoStatus.FAILED)  # FAILED de outra campanha não volta para a fila

    def test_exception_in_geocoder_does_not_abort_the_run(self):
        first = make_voter(self.a, self.cabo, 1, geo_status=GeoStatus.PENDING, cep="13010000")
        second = make_voter(self.a, self.cabo, 2, geo_status=GeoStatus.PENDING, cep="13010000")

        def flaky(voter_id):
            if voter_id == first.pk:
                raise RuntimeError("rede indisponível")
            fake_geocode(voter_id)

        with mock.patch("apps.mapview.geocoding.geocode_voter", side_effect=flaky), self.assertLogs("apps.mapview.geocoding", "ERROR"):
            response = client_for(self.admin).post(URL)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.geo_status, GeoStatus.FAILED)
        self.assertEqual(second.geo_status, GeoStatus.OK)
        self.assertEqual(response.status_code, 302)

    def test_writes_audit_without_personal_data(self):
        make_voter(self.a, self.cabo, 1, geo_status=GeoStatus.PENDING, cep="13010000")
        with patched():
            client_for(self.admin).post(URL)
        log = AuditLog.objects.get(action="voter.geocode")
        self.assertEqual(log.campaign_id, self.a.pk)
        self.assertEqual(log.user_id, self.admin.pk)
        self.assertEqual(log.details, {"processed": 1, "located": 1, "failed": 0, "remaining": 0})

    def test_redirect_keeps_only_valid_filters(self):
        with patched():
            response = client_for(self.admin).post(
                URL, {"qs": "bairro=Centro&geo=1&next=https://evil.example&cidade=Campinas&apoio=XPTO"}
            )
        self.assertEqual(response.status_code, 302)
        location = response["Location"]
        self.assertTrue(location.startswith(MAP + "?"))
        self.assertIn("bairro=Centro", location)
        self.assertIn("cidade=Campinas", location)
        self.assertNotIn("evil", location)
        self.assertNotIn("geo=", location)
        self.assertNotIn("XPTO", location)

    def test_redirect_is_always_the_map(self):
        with patched():
            for payload in ({"qs": "//evil.example/x"}, {"next": "https://evil.example"}, {"qs": "x" * 5000}):
                response = client_for(self.admin).post(URL, payload)
                self.assertEqual(response["Location"], MAP, payload)

    def test_concurrent_run_is_blocked_by_lock(self):
        pending = make_voter(self.a, self.cabo, 1, geo_status=GeoStatus.PENDING, cep="13010000")
        cache.set(f"mapview:geocode:{self.a.pk}", 1, 60)
        with patched() as geocode:
            response = client_for(self.admin).post(URL)
        geocode.assert_not_called()
        self.assertEqual(self.messages(response)[0][0], "warning")
        pending.refresh_from_db()
        self.assertEqual(pending.geo_status, GeoStatus.PENDING)

    def test_lock_is_released_after_run(self):
        make_voter(self.a, self.cabo, 1, geo_status=GeoStatus.PENDING, cep="13010000")
        with patched():
            client_for(self.admin).post(URL)
        self.assertIsNone(cache.get(f"mapview:geocode:{self.a.pk}"))

    def test_rate_limit(self):
        with patched():
            client = client_for(self.admin)
            for _ in range(12):
                client.post(URL)
            response = client.post(URL)
        level, text = self.messages(response)[-1]
        self.assertEqual(level, "error")
        self.assertIn("Muitas solicitações", text)
        self.assertEqual(response["Location"], MAP)


class RunCampaignGeocodingTests(GeocodeBase):
    def test_pending_come_before_failed(self):
        failed = make_voter(self.a, self.cabo, 1, geo_status=GeoStatus.FAILED, cep="13010000")
        pending = make_voter(self.a, self.cabo, 2, geo_status=GeoStatus.PENDING, cep="13010000")
        with patched() as geocode:
            result = run_campaign_geocoding(self.admin, limit=1)
        geocode.assert_called_once_with(pending.pk)
        self.assertEqual(result.processed, 1)
        failed.refresh_from_db()
        self.assertEqual(failed.geo_status, GeoStatus.PENDING)  # voltou para a fila, o worker processa

    def test_result_counts(self):
        make_voter(self.a, self.cabo, 1, geo_status=GeoStatus.PENDING, cep="13010000")
        make_voter(self.a, self.cabo, 2, geo_status=GeoStatus.PENDING, cep="00000000")
        make_voter(self.a, self.cabo, 3, geo_status=GeoStatus.PENDING, cep="13010000")
        with patched():
            result = run_campaign_geocoding(self.admin, limit=2)
        self.assertEqual(result, GeocodeRunResult(processed=2, located=1, failed=1, remaining=1))

    def test_time_budget_stops_before_the_next_voter(self):
        for i in range(1, 4):
            make_voter(self.a, self.cabo, i, geo_status=GeoStatus.PENDING, cep="13010000")
        with patched() as geocode:
            result = run_campaign_geocoding(self.admin, time_budget=-1)
        geocode.assert_not_called()
        self.assertEqual((result.processed, result.remaining), (0, 3))


class MessageTests(SimpleTestCase):
    def test_nothing_processed(self):
        self.assertEqual(geocode_run_message(GeocodeRunResult(0, 0, 0, 0)), ("info", "Não há apoiadores pendentes de localização."))

    def test_plurals(self):
        self.assertEqual(geocode_run_message(GeocodeRunResult(1, 1, 0, 0)), ("success", "1 apoiador localizado."))
        self.assertEqual(geocode_run_message(GeocodeRunResult(2, 2, 0, 0)), ("success", "2 apoiadores localizados."))

    def test_all_failed_is_a_warning(self):
        level, text = geocode_run_message(GeocodeRunResult(2, 0, 2, 0))
        self.assertEqual(level, "warning")
        self.assertIn("2 endereços não encontrados", text)

    def test_remaining_queue_note(self):
        _, one = geocode_run_message(GeocodeRunResult(1, 1, 0, 1))
        self.assertIn("1 apoiador continua na fila", one)
        _, many = geocode_run_message(GeocodeRunResult(15, 15, 0, 1200))
        self.assertIn("1.200 apoiadores continuam na fila", many)
