"""Geocodificação: nenhuma coordenada é aceita fora do bairro do apoiador.

Regressão do caso real: Av. Brasil, Guadalupe (RJ). O BrasilAPI devolve o MESMO ponto do centro do Rio (perto da
Av. Passos) para todos os CEPs da avenida, e uma busca só pelo nome da avenida cai em Campo Grande."""

from unittest import mock

from django.test import SimpleTestCase, TestCase

from apps.geo import geocode
from apps.geo.cep import CepInfo
from apps.geo.geocode import Area, GeoPoint, geocode_address
from apps.geo.models import CepCache

# Referências aproximadas (as mesmas do diagnóstico com os serviços reais)
RIO_CITY = {"lat": "-22.9110", "lon": "-43.4440", "boundingbox": ["-23.0830", "-22.7460", "-43.7960", "-43.0990"]}
GUADALUPE = {"lat": "-22.8376", "lon": "-43.3752", "boundingbox": ["-22.8500", "-22.8250", "-43.3900", "-43.3600"]}
GUADALUPE_STREET = {"lat": "-22.8402", "lon": "-43.3705"}  # trecho da Av. Brasil DENTRO de Guadalupe
CAMPO_GRANDE_STREET = {"lat": "-22.8726", "lon": "-43.6063"}  # outro trecho da mesma avenida (21 km dali)
BRASILAPI_WRONG = (-22.90642, -43.18223)  # ponto do BrasilAPI para a Av. Brasil: Centro do Rio


class BrasilApiStub:
    def __init__(self, point):
        self.latitude, self.longitude = point if point else (None, None)


def fake_nominatim(street_results=None, postal_results=None, fail_street=False):
    """Simula o Nominatim conforme o tipo de consulta (área por texto livre, rua com viewbox, código postal)."""
    calls = []

    def fn(**params):
        calls.append(params)
        if "q" in params:  # área
            if params["q"].startswith("Guadalupe"):
                return [GUADALUPE]
            return [RIO_CITY]
        if "street" in params:
            return None if fail_street else (street_results or [])
        if "postalcode" in params:
            return postal_results or []
        return []

    fn.calls = calls
    return fn


class AreaTests(SimpleTestCase):
    def test_bairro_box_is_padded_and_has_a_minimum_size(self):
        point_only = Area(-22.8376, -43.3752, (-22.8376, -43.3752, -22.8376, -43.3752), "bairro")  # caixa de um nó
        self.assertTrue(point_only.contains(-22.8376 + 0.01, -43.3752))  # ~1,1 km: dentro do mínimo de 1,5 km
        self.assertFalse(point_only.contains(-22.90642, -43.18223))  # Centro do Rio

    def test_city_level_is_wider(self):
        city = Area(-22.9110, -43.4440, (-23.0830, -43.7960, -22.7460, -43.0990), "cidade")
        self.assertTrue(city.contains(*BRASILAPI_WRONG))
        self.assertFalse(city.contains(-23.5505, -46.6333))  # São Paulo


class GeocodeAddressTests(TestCase):
    def run_geocode(self, nominatim, brasilapi=None, cep_info=None, **address):
        base = dict(cep="21670000", street="Avenida Brasil", neighborhood="Guadalupe", city="Rio de Janeiro", state="RJ")
        base.update(address)
        with (
            mock.patch.object(geocode, "_nominatim", nominatim),
            mock.patch.object(geocode, "from_brasilapi", return_value=BrasilApiStub(brasilapi) if brasilapi else None),
            mock.patch.object(geocode, "lookup_cep", return_value=cep_info),
        ):
            return geocode_address(**base)

    def test_street_inside_the_bairro_wins(self):
        point = self.run_geocode(fake_nominatim(street_results=[GUADALUPE_STREET]), brasilapi=BRASILAPI_WRONG)
        self.assertEqual((point.precision, point.source), ("OK", "nominatim-rua"))
        self.assertAlmostEqual(point.latitude, -22.8402)

    def test_street_search_is_bounded_to_the_bairro_box(self):
        nominatim = fake_nominatim(street_results=[GUADALUPE_STREET])
        self.run_geocode(nominatim)
        street_call = next(c for c in nominatim.calls if "street" in c)
        self.assertEqual(street_call["bounded"], "1")
        west, north, east, south = (float(v) for v in street_call["viewbox"].split(","))
        self.assertTrue(south < -22.8376 < north and west < -43.3752 < east)  # a caixa envolve Guadalupe

    def test_a_street_result_outside_the_bairro_is_rejected(self):
        point = self.run_geocode(fake_nominatim(street_results=[CAMPO_GRANDE_STREET]))
        self.assertEqual(point.source, "nominatim-bairro")  # caiu no centro do bairro, não em Campo Grande
        self.assertAlmostEqual(point.longitude, -43.3752)

    def test_wrong_brasilapi_point_is_rejected_and_falls_back_to_the_bairro_center(self):
        """O caso do usuário: BrasilAPI aponta para o Centro do Rio; o apoiador mora em Guadalupe."""
        point = self.run_geocode(fake_nominatim(), brasilapi=BRASILAPI_WRONG)
        self.assertEqual((point.precision, point.source), ("APPROXIMATE", "nominatim-bairro"))
        self.assertAlmostEqual(point.latitude, -22.8376, places=3)
        self.assertAlmostEqual(point.longitude, -43.3752, places=3)

    def test_correct_brasilapi_point_inside_the_bairro_is_accepted(self):
        point = self.run_geocode(fake_nominatim(), brasilapi=(-22.8410, -43.3720))
        self.assertEqual((point.precision, point.source), ("OK", "brasilapi"))

    def test_postal_code_result_is_used_only_when_inside_the_bairro(self):
        ok = self.run_geocode(fake_nominatim(postal_results=[{"lat": "-22.8390", "lon": "-43.3730"}]))
        self.assertEqual(ok.source, "nominatim-cep")
        CepCache.objects.all().delete()
        outside = self.run_geocode(fake_nominatim(postal_results=[{"lat": "-22.9064", "lon": "-43.1822"}]))
        self.assertEqual(outside.source, "nominatim-bairro")

    def test_missing_bairro_is_completed_from_the_cep(self):
        info = CepInfo(cep="21670000", street="Avenida Brasil", neighborhood="Guadalupe", city="Rio de Janeiro", state="RJ")
        point = self.run_geocode(fake_nominatim(street_results=[GUADALUPE_STREET]), cep_info=info, neighborhood="", street="")
        self.assertEqual(point.source, "nominatim-rua")

    def test_without_bairro_it_validates_against_the_city(self):
        point = self.run_geocode(fake_nominatim(street_results=[CAMPO_GRANDE_STREET]), neighborhood="", cep="")
        self.assertEqual((point.precision, point.source), ("OK", "nominatim-rua"))  # sem bairro, qualquer ponto da cidade vale

    def test_city_center_is_the_last_resort(self):
        def only_city(**params):
            if "q" in params:
                return [] if params["q"].startswith("Guadalupe") else [RIO_CITY]
            return []

        point = self.run_geocode(only_city)
        self.assertEqual((point.precision, point.source), ("APPROXIMATE", "nominatim-cidade"))

    def test_results_are_cached_and_reused(self):
        nominatim = fake_nominatim(street_results=[GUADALUPE_STREET])
        first = self.run_geocode(nominatim)
        calls_after_first = len(nominatim.calls)
        again = self.run_geocode(nominatim)
        self.assertEqual(len(nominatim.calls), calls_after_first)  # nada novo na rede
        self.assertEqual((again.latitude, again.source), (first.latitude, first.source))

    def test_old_cache_entries_without_a_box_are_refreshed(self):
        CepCache.objects.create(key="A:rj:rio-de-janeiro:guadalupe", latitude=-22.90, longitude=-43.18, geo_source="nominatim-bairro")
        point = self.run_geocode(fake_nominatim())
        self.assertAlmostEqual(point.latitude, -22.8376, places=3)  # ignorou o centro errado que estava em cache

    def test_network_failure_is_not_cached_as_a_final_answer(self):
        def down(**params):
            return None

        self.assertIsNone(self.run_geocode(down))
        self.assertFalse(CepCache.objects.filter(key__startswith="P:").exists())
        self.assertIsNotNone(self.run_geocode(fake_nominatim(street_results=[GUADALUPE_STREET])))  # tenta de novo e funciona

    def test_without_city_nothing_is_done(self):
        self.assertIsNone(self.run_geocode(fake_nominatim(), city="", cep=""))

    def test_long_cache_keys_stay_within_the_column_limit(self):
        key = geocode._point_key("", "Rua " + "x" * 200, "Bairro " + "y" * 90, "Cidade " + "z" * 90, "RJ")
        self.assertLessEqual(len(key), 120)
        self.assertEqual(key, geocode._point_key("", "Rua " + "x" * 200, "Bairro " + "y" * 90, "Cidade " + "z" * 90, "RJ"))


class GeocodeVoterTests(TestCase):
    def test_voter_gets_the_validated_point_and_status(self):
        from apps.campaigns.bootstrap import bootstrap_campaign
        from apps.campaigns.models import Campaign
        from apps.accounts.models import User
        from apps.voters.models import Voter

        campaign = Campaign.objects.create(slug="geo", candidate_name="G", ballot_name="G", office="VEREADOR", election_year=2026)
        bootstrap_campaign(campaign)
        admin = User.objects.create_user("a@geo.com", "Senha@12345", name="A", role="ADMIN", campaign=campaign)
        voter = Voter.objects.create(
            campaign=campaign, registered_by=admin, name="Maria", phone="5521999990001", cep="21670000",
            street="Avenida Brasil", neighborhood="Guadalupe", city="Rio de Janeiro", state="RJ",
            latitude=-22.90642, longitude=-43.18223, geo_status="OK",  # ponto ERRADO (Centro) herdado da versão antiga
        )  # fmt: skip
        with (
            mock.patch.object(geocode, "_nominatim", fake_nominatim(street_results=[CAMPO_GRANDE_STREET])),
            mock.patch.object(geocode, "from_brasilapi", return_value=BrasilApiStub(BRASILAPI_WRONG)),
            mock.patch.object(geocode, "lookup_cep", return_value=None),
        ):
            geocode.geocode_voter(voter.pk)
        voter.refresh_from_db()
        self.assertEqual(voter.geo_status, "APPROXIMATE")
        self.assertAlmostEqual(voter.latitude, -22.8376, places=3)  # corrigido: agora em Guadalupe
        self.assertIsInstance(GeoPoint(0, 0, "OK", "x"), GeoPoint)
