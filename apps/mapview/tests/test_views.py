"""Página e endpoint JSON do mapa: permissões, escopo hierárquico, isolamento entre campanhas e privacidade."""

import json

from django.test import Client, TestCase

from apps.accounts.models import RolePermission, User, UserPermission
from apps.core.constants import GeoStatus, Role, SupportLevel

from .helpers import PASSWORD, client_for, fast_hashing, make_campaign, make_user, make_voter

DATA_URL = "/api/painel/mapa/dados/"
PAGE_URL = "/painel/mapa/"

# Coordenadas (Campinas/SP, aproximadas)
CENTRO = (-22.9056, -47.0608)
CAMBUI = (-22.8950, -47.0500)
BARAO = (-22.8200, -47.0700)


@fast_hashing
class MapBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = make_campaign("alfa")
        cls.b = make_campaign("beta")
        cls.admin = make_user(cls.a, "admin@a.com", Role.ADMIN, name="Admin A")
        cls.coord1 = make_user(cls.a, "coord1@a.com", Role.COORDENADOR, parent=cls.admin, name="Coord Um")
        cls.coord2 = make_user(cls.a, "coord2@a.com", Role.COORDENADOR, parent=cls.admin, name="Coord Dois")
        cls.cabo1 = make_user(cls.a, "cabo1@a.com", Role.CABO, parent=cls.coord1, name="Cabo Um")
        cls.cabo2 = make_user(cls.a, "cabo2@a.com", Role.CABO, parent=cls.coord2, name="Cabo Dois")
        cls.admin_b = make_user(cls.b, "admin@b.com", Role.ADMIN, name="Admin B")
        cls.superuser = User.objects.create_superuser("super@x.com", PASSWORD)

        def geo(n, by, point, bairro, status=GeoStatus.OK, **extra):
            return make_voter(
                cls.a, by, n, latitude=point[0], longitude=point[1], geo_status=status,
                neighborhood=bairro, city="Campinas", **extra,
            )

        # cabo1 (rede da coord1): 2 no Centro (1 apoiador apto a WhatsApp), 1 no Cambuí (aproximado)
        cls.v1 = geo(1, cls.cabo1, CENTRO, "Centro", support_level=SupportLevel.APOIADOR, whatsapp_opt_in=True)
        cls.v2 = geo(2, cls.cabo1, CENTRO, "Centro")
        cls.v3 = geo(3, cls.cabo1, CAMBUI, "Cambuí", status=GeoStatus.APPROXIMATE)
        # cabo2 (rede da coord2)
        cls.v4 = geo(4, cls.cabo2, BARAO, "Barão Geraldo")
        cls.v5 = geo(5, cls.cabo2, CENTRO, "Centro")
        # sem localização
        cls.v6 = make_voter(cls.a, cls.cabo2, 6, neighborhood="Sousas", city="Campinas", geo_status=GeoStatus.PENDING)
        cls.v7 = make_voter(cls.a, cls.coord1, 7, neighborhood="", city="", geo_status=GeoStatus.FAILED)
        # outra campanha
        cls.vb = make_voter(
            cls.b, cls.admin_b, 8, latitude=-23.5, longitude=-46.6, geo_status=GeoStatus.OK,
            neighborhood="Pinheiros", city="São Paulo",
        )

    def api(self, user, query=""):
        return client_for(user).get(DATA_URL + (f"?{query}" if query else ""))

    def payload(self, user, query=""):
        response = self.api(user, query)
        self.assertEqual(response.status_code, 200, response.content[:300])
        return response.json()

    @staticmethod
    def names(payload):
        return {n["name"] for n in payload["neighborhoods"]}


class PageAccessTests(MapBase):
    def test_anonymous_is_redirected_to_login(self):
        response = Client().get(PAGE_URL)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/login/?next="))

    def test_all_campaign_roles_can_open_the_page(self):
        for user in (self.admin, self.coord1, self.cabo1):
            response = client_for(user).get(PAGE_URL)
            self.assertEqual(response.status_code, 200, user.role)
            self.assertContains(response, "Mapa territorial")
            self.assertContains(response, 'id="map-config"')
            self.assertContains(response, "vendor/leaflet/leaflet.js")
            self.assertContains(response, "js/mapview/map.js")

    def test_super_admin_is_sent_to_super_panel(self):
        response = client_for(self.superuser).get(PAGE_URL)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/super/")

    def test_role_without_map_permission_gets_403(self):
        RolePermission.objects.filter(campaign=self.a, role=Role.CABO, module="mapa").update(can_view=False)
        self.assertEqual(client_for(self.cabo1).get(PAGE_URL).status_code, 403)
        self.assertEqual(client_for(self.coord1).get(PAGE_URL).status_code, 200)  # outro papel continua com acesso

    def test_user_override_revokes_access(self):
        UserPermission.objects.create(user=self.coord1, module="mapa", can_view=False)
        self.assertEqual(client_for(self.coord1).get(PAGE_URL).status_code, 403)
        self.assertEqual(client_for(self.coord2).get(PAGE_URL).status_code, 200)

    def test_admin_keeps_access_even_if_role_rows_are_removed(self):
        RolePermission.objects.filter(campaign=self.a).delete()
        self.assertEqual(client_for(self.admin).get(PAGE_URL).status_code, 200)

    def test_post_is_not_allowed(self):
        self.assertEqual(client_for(self.admin).post(PAGE_URL).status_code, 405)


class PageContentTests(MapBase):
    def test_has_geo_filter_is_hidden_and_other_filters_are_present(self):
        response = client_for(self.admin).get(PAGE_URL)
        self.assertNotContains(response, 'id="vf-geo"')
        self.assertNotContains(response, "Localização no mapa")
        self.assertContains(response, "Todos os bairros")
        self.assertContains(response, 'name="idade_min"')

    def test_map_config_exposes_basemaps_and_urls(self):
        response = client_for(self.admin).get(PAGE_URL)
        config = response.context["map_config"]
        self.assertEqual(config["dataUrl"], DATA_URL)
        self.assertEqual(config["votersUrl"], "/painel/eleitores/")
        self.assertEqual(config["defaultMode"], "bairros")
        self.assertIn("openstreetmap.org", config["basemaps"]["ruas"]["url"])
        self.assertIn("openstreetmap.org", config["basemaps"]["claro"]["url"])
        self.assertEqual(config["basemaps"]["claro"]["className"], "efind-tiles-light")
        self.assertContains(response, "dados/")

    def test_page_has_no_voter_personal_data(self):
        for user in (self.admin, self.cabo1):
            response = client_for(user).get(PAGE_URL)
            for secret in ("Eleitor Secreto", "5511900"):
                self.assertNotContains(response, secret)

    def test_active_filters_are_kept_and_has_geo_is_dropped(self):
        response = client_for(self.admin).get(PAGE_URL + "?bairro=Centro&geo=1")
        self.assertNotIn("has_geo", response.context["filters"])
        self.assertEqual(response.context["filters"]["neighborhoods"], ["Centro"])
        self.assertEqual(response.context["active_filters"], 1)

    def test_geocoding_card_is_admin_only(self):
        admin_page = client_for(self.admin).get(PAGE_URL)
        self.assertContains(admin_page, "Localizar pendentes agora")
        self.assertContains(admin_page, "/painel/mapa/localizar-pendentes/")
        for user in (self.coord1, self.cabo1):
            page = client_for(user).get(PAGE_URL)
            self.assertNotContains(page, "Localizar pendentes agora")
            self.assertIsNone(page.context["geo_queue"])

    def test_geocoding_card_counts_only_own_campaign(self):
        make_voter(self.b, self.admin_b, 9, geo_status=GeoStatus.PENDING)  # outra campanha: não conta
        queue = client_for(self.admin).get(PAGE_URL).context["geo_queue"]
        self.assertEqual(queue, {"pending": 1, "failed": 1, "total": 2})
        other = client_for(self.admin_b).get(PAGE_URL).context["geo_queue"]
        self.assertEqual(other, {"pending": 1, "failed": 0, "total": 1})


class ApiAccessTests(MapBase):
    def test_anonymous_gets_401_json(self):
        response = Client().get(DATA_URL)
        self.assertEqual(response.status_code, 401)
        self.assertIn("error", response.json())

    def test_super_admin_gets_403_json(self):
        response = self.api(self.superuser)
        self.assertEqual(response.status_code, 403)
        self.assertIn("error", response.json())

    def test_role_without_permission_gets_403_json(self):
        RolePermission.objects.filter(campaign=self.a, role=Role.CABO, module="mapa").update(can_view=False)
        response = self.api(self.cabo1)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertNotIn("neighborhoods", response.json())

    def test_only_get_is_allowed(self):
        client = client_for(self.admin)
        for method in ("post", "put", "delete", "patch"):
            self.assertEqual(getattr(client, method)(DATA_URL).status_code, 405, method)

    def test_response_is_not_cached(self):
        response = self.api(self.admin)
        self.assertIn("no-store", response["Cache-Control"])


class ApiDataTests(MapBase):
    def test_admin_sees_whole_campaign(self):
        data = self.payload(self.admin)
        self.assertEqual(data["totals"], {"voters": 7, "with_geo": 5, "without_geo": 2, "approximate": 1})
        self.assertEqual(self.names(data), {"Centro", "Cambuí", "Barão Geraldo"})
        self.assertEqual(len(data["points"]), 5)
        self.assertFalse(data["truncated"])
        self.assertEqual(data["bounds"], [[-22.9056, -47.07], [-22.82, -47.05]])
        self.assertTrue(data["can_view_voters"])

    def test_response_shape(self):
        data = self.payload(self.admin)
        self.assertEqual(
            set(data),
            {"totals", "neighborhoods", "neighborhoods_without_geo", "points", "truncated", "bounds", "can_view_voters", "legend"},
        )
        centro = next(n for n in data["neighborhoods"] if n["name"] == "Centro")
        for key in ("name", "city", "count", "lat", "lng", "messageable", "supporters", "top_members", "color", "radius", "key"):
            self.assertIn(key, centro)
        self.assertEqual((centro["count"], centro["supporters"], centro["messageable"]), (3, 1, 0))
        self.assertEqual(centro["city"], "Campinas")
        self.assertEqual(data["neighborhoods"][0]["name"], "Centro")  # maior primeiro

    def test_messageable_requires_full_consent(self):
        # whatsapp_opt_in sem consent_at não é "apto a WhatsApp"
        centro = next(n for n in self.payload(self.admin)["neighborhoods"] if n["name"] == "Centro")
        self.assertEqual(centro["messageable"], 0)
        from django.utils import timezone

        type(self.v1).objects.filter(pk=self.v1.pk).update(consent_at=timezone.now())
        centro = next(n for n in self.payload(self.admin)["neighborhoods"] if n["name"] == "Centro")
        self.assertEqual(centro["messageable"], 1)
        type(self.v1).objects.filter(pk=self.v1.pk).update(opt_out_at=timezone.now())  # descadastrou
        centro = next(n for n in self.payload(self.admin)["neighborhoods"] if n["name"] == "Centro")
        self.assertEqual(centro["messageable"], 0)

    def test_top_members_are_registrars(self):
        centro = next(n for n in self.payload(self.admin)["neighborhoods"] if n["name"] == "Centro")
        self.assertEqual(centro["top_members"], [{"name": "Cabo Um", "count": 2}, {"name": "Cabo Dois", "count": 1}])

    def test_without_geo_lists(self):
        data = self.payload(self.admin)
        without = {n["name"]: n["count"] for n in data["neighborhoods_without_geo"]}
        self.assertEqual(without, {"Sousas": 1, "Bairro não informado": 1})

    def test_coordinator_sees_only_own_network(self):
        data = self.payload(self.coord1)
        self.assertEqual(data["totals"]["voters"], 4)  # 3 do cabo1 + 1 dele mesmo
        self.assertEqual(self.names(data), {"Centro", "Cambuí"})
        point_ids = {p["id"] for p in data["points"]}
        self.assertEqual(point_ids, {str(self.v1.pk), str(self.v2.pk), str(self.v3.pk)})
        self.assertEqual(next(n for n in data["neighborhoods"] if n["name"] == "Centro")["count"], 2)

    def test_cabo_sees_only_own_voters(self):
        data = self.payload(self.cabo2)
        self.assertEqual(data["totals"]["voters"], 3)
        self.assertEqual({p["id"] for p in data["points"]}, {str(self.v4.pk), str(self.v5.pk)})
        self.assertEqual(self.names(data), {"Barão Geraldo", "Centro"})
        centro = next(n for n in data["neighborhoods"] if n["name"] == "Centro")
        self.assertEqual(centro["count"], 1)
        self.assertEqual(centro["top_members"], [{"name": "Cabo Dois", "count": 1}])

    def test_other_campaign_never_leaks(self):
        for user in (self.admin, self.coord1, self.cabo1, self.coord2, self.cabo2):
            response = self.api(user)
            body = response.content.decode()
            self.assertNotIn(str(self.vb.pk), body, user.role)
            self.assertNotIn("Pinheiros", body, user.role)
            self.assertNotIn("Admin B", body, user.role)
        data = self.payload(self.admin_b)
        self.assertEqual(data["totals"], {"voters": 1, "with_geo": 1, "without_geo": 0, "approximate": 0})
        self.assertEqual(self.names(data), {"Pinheiros"})
        self.assertNotIn("Centro", json.dumps(data))

    def test_never_returns_names_phones_or_emails(self):
        make_voter(self.a, self.cabo1, 10, latitude=-22.9, longitude=-47.0, geo_status=GeoStatus.OK,
                   neighborhood="Taquaral", city="Campinas", email="secreto@exemplo.com")
        for user in (self.admin, self.coord1, self.cabo1):
            body = self.api(user).content.decode()
            for secret in ("Eleitor Secreto", "5511900", "secreto@exemplo.com", "@exemplo"):
                self.assertNotIn(secret, body, user.role)
        for point in self.payload(self.admin)["points"]:
            self.assertEqual(set(point), {"id", "lat", "lng"})

    def test_filters_by_neighborhood_and_city(self):
        data = self.payload(self.admin, "bairro=Centro")
        self.assertEqual(data["totals"]["voters"], 3)
        self.assertEqual(self.names(data), {"Centro"})
        self.assertEqual(self.payload(self.admin, "cidade=Valinhos")["totals"]["voters"], 0)

    def test_filters_by_support_level_and_registrar(self):
        self.assertEqual(self.payload(self.admin, "apoio=APOIADOR")["totals"]["voters"], 1)
        data = self.payload(self.admin, f"cabo={self.cabo2.pk}")
        self.assertEqual(data["totals"]["voters"], 3)

    def test_filter_cannot_widen_scope(self):
        data = self.payload(self.cabo1, f"cabo={self.cabo2.pk}")
        self.assertEqual(data["totals"]["voters"], 0)
        self.assertEqual(data["points"], [])
        data = self.payload(self.admin, f"cabo={self.admin_b.pk}")  # id de outra campanha
        self.assertEqual(data["totals"]["voters"], 0)

    def test_coordinator_filter_respects_scope(self):
        data = self.payload(self.coord1, f"coord={self.coord2.pk}")
        self.assertEqual(data["totals"]["voters"], 0)

    def test_has_geo_filter_is_ignored(self):
        self.assertEqual(self.payload(self.admin, "geo=1")["totals"]["voters"], 7)
        self.assertEqual(self.payload(self.admin, "geo=0")["totals"]["voters"], 7)

    def test_invalid_filter_values_are_ignored_not_fatal(self):
        data = self.payload(self.admin, "cabo=nao-e-uuid&idade_min=abc&de=ontem&apoio=INVENTADO&bairro=")
        self.assertEqual(data["totals"]["voters"], 7)

    def test_injection_like_input_is_harmless(self):
        data = self.payload(self.admin, "bairro=" + "'%20OR%201=1%20--")
        self.assertEqual(data["totals"]["voters"], 0)

    def test_empty_campaign(self):
        c = make_campaign("vazia")
        admin = make_user(c, "admin@vazia.com", Role.ADMIN)
        data = self.payload(admin)
        self.assertEqual(data["totals"], {"voters": 0, "with_geo": 0, "without_geo": 0, "approximate": 0})
        self.assertEqual(data["neighborhoods"], [])
        self.assertIsNone(data["bounds"])
        self.assertEqual(data["legend"]["bins"], [])

    def test_can_view_voters_follows_voters_permission(self):
        self.assertTrue(self.payload(self.cabo1)["can_view_voters"])
        RolePermission.objects.filter(campaign=self.a, role=Role.CABO, module="eleitores").update(can_view=False)
        data = self.payload(self.cabo1)
        self.assertFalse(data["can_view_voters"])
        self.assertEqual(data["totals"]["voters"], 3)  # o mapa continua funcionando
        self.assertTrue(self.payload(self.admin)["can_view_voters"])

    def test_query_count_does_not_grow_with_voters(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def count():
            with CaptureQueriesContext(connection) as ctx:
                self.assertEqual(self.api(self.admin).status_code, 200)
            return len(ctx)

        baseline = count()
        for i in range(20, 60):
            make_voter(self.a, self.cabo1, i, latitude=-22.9, longitude=-47.0, geo_status=GeoStatus.OK,
                       neighborhood=f"Bairro {i % 7}", city="Campinas")
        self.assertEqual(count(), baseline)

    def test_point_cap_flag_in_endpoint(self):
        from unittest import mock

        with mock.patch("apps.mapview.aggregate.MAP_POINT_LIMIT", 2):
            data = self.payload(self.admin)
        self.assertEqual(len(data["points"]), 2)
        self.assertTrue(data["truncated"])
        self.assertEqual(data["totals"]["with_geo"], 5)
