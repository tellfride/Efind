"""Páginas, fluxos POST, API JSON e regras de segurança dos dashboards."""

import json
import uuid
from unittest import mock

from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import RolePermission
from apps.auditlog.models import AuditLog
from apps.campaigns.models import Campaign
from apps.core.constants import Role
from apps.core.ratelimit import RateLimitResult
from apps.dashboards import views
from apps.dashboards.models import Dashboard
from apps.dashboards.presets import DASHBOARD_PRESETS, preset_widgets
from apps.dashboards.services import MAX_OWN_DASHBOARDS

from .helpers import client_for, fast_hashing, make_campaign, make_user, make_voter

DATA_URL = "/api/painel/dashboard/data/"
FILTERS_URL = "/api/painel/dashboard/filtros/"


def post_json(client, url, body):
    return client.post(url, data=json.dumps(body), content_type="application/json")


def widget(id_, type_="kpi_total", size="sm", **config):
    return {"id": id_, "type": type_, "size": size, "config": config}


@fast_hashing
class ViewBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = make_campaign("alfa")
        cls.b = make_campaign("beta")
        cls.admin = make_user(cls.a, "admin@a.com", Role.ADMIN, name="Maria Admin")
        cls.coord1 = make_user(cls.a, "coord1@a.com", Role.COORDENADOR, parent=cls.admin, name="Carlos Coord")
        cls.coord2 = make_user(cls.a, "coord2@a.com", Role.COORDENADOR, parent=cls.admin, name="Dora Coord")
        cls.cabo1 = make_user(cls.a, "cabo1@a.com", Role.CABO, parent=cls.coord1, name="Ana Cabo")
        cls.cabo2 = make_user(cls.a, "cabo2@a.com", Role.CABO, parent=cls.coord2, name="Bia Cabo")
        cls.admin_b = make_user(cls.b, "admin@b.com", Role.ADMIN, name="Admin Beta")
        cls.cabo_b = make_user(cls.b, "cabo@b.com", Role.CABO, parent=cls.admin_b)
        from apps.accounts.models import User

        cls.superuser = User.objects.create_superuser("super@x.com", "Senha@12345")

        cls.default = Dashboard.objects.get(campaign=cls.a, is_default=True)  # "Visão geral" (compartilhado, sem dono)
        cls.shared_team = Dashboard.objects.get(campaign=cls.a, name="Desempenho da equipe")
        cls.private_coord1 = Dashboard.objects.create(
            campaign=cls.a, owner=cls.coord1, name="Painel do Carlos", widgets=[widget("a1", "kpi_total")]
        )
        cls.private_cabo1 = Dashboard.objects.create(
            campaign=cls.a, owner=cls.cabo1, name="Painel da Ana", widgets=[widget("b1", "kpi_total")]
        )
        cls.beta_default = Dashboard.objects.get(campaign=cls.b, is_default=True)
        cls.beta_private = Dashboard.objects.create(campaign=cls.b, owner=cls.admin_b, name="Segredo da Beta", widgets=[])

        make_voter(cls.a, cls.cabo1, 1, neighborhood="Centro")
        make_voter(cls.a, cls.cabo2, 2, neighborhood="Taquaral")
        make_voter(cls.b, cls.cabo_b, 3, neighborhood="Segredo")

    def audit_actions(self):
        return list(AuditLog.objects.filter(campaign=self.a).values_list("action", flat=True))


class AnonymousAndRoleSmokeTests(ViewBase):
    def test_anonymous_is_sent_to_login(self):
        client = Client()
        for url in (
            "/painel/",
            "/painel/dashboards/",
            "/painel/dashboards/novo/",
            f"/painel/dashboards/{self.default.pk}/",
            f"/painel/dashboards/{self.default.pk}/editar/",
        ):
            response = client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertTrue(response["Location"].startswith("/login/?next="), url)

    def test_anonymous_post_endpoints_do_not_work(self):
        client = Client()
        for url in (
            f"/painel/dashboards/{self.default.pk}/excluir/",
            f"/painel/dashboards/{self.default.pk}/duplicar/",
            f"/painel/dashboards/{self.default.pk}/padrao/",
            "/painel/dashboards/padroes/",
        ):
            response = client.post(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertTrue(response["Location"].startswith("/login/"), url)
        self.assertTrue(Dashboard.objects.filter(pk=self.default.pk).exists())

    def test_anonymous_api_returns_json_401(self):
        client = Client()
        for url in (DATA_URL, FILTERS_URL, f"/api/painel/dashboard/{self.default.pk}/salvar/"):
            response = client.post(url, data="{}", content_type="application/json")
            self.assertEqual(response.status_code, 401, url)
            self.assertIn("error", response.json())

    def test_pages_render_for_each_role(self):
        for user in (self.admin, self.coord1, self.cabo1):
            client = client_for(user)
            for url in ("/painel/", "/painel/dashboards/", f"/painel/dashboards/{self.default.pk}/"):
                response = client.get(url)
                self.assertEqual(response.status_code, 200, f"{user.role} {url}")
                if url != "/painel/dashboards/":  # a listagem não carrega o desenhista de widgets
                    self.assertContains(response, 'id="dash-config"')
                    self.assertContains(response, 'id="dash-icons"')

    def test_create_page_by_permission(self):
        self.assertEqual(client_for(self.admin).get("/painel/dashboards/novo/").status_code, 200)
        self.assertEqual(client_for(self.coord1).get("/painel/dashboards/novo/").status_code, 200)
        self.assertEqual(client_for(self.cabo1).get("/painel/dashboards/novo/").status_code, 403)  # cabo só visualiza

    def test_edit_page_by_permission(self):
        self.assertContains(client_for(self.admin).get(f"/painel/dashboards/{self.default.pk}/editar/"), "Adicionar widget")
        # coordenador: dashboard compartilhado → 403; o próprio → 200
        coord = client_for(self.coord1)
        self.assertEqual(coord.get(f"/painel/dashboards/{self.default.pk}/editar/").status_code, 403)
        self.assertEqual(coord.get(f"/painel/dashboards/{self.private_coord1.pk}/editar/").status_code, 200)
        # cabo não tem dashboard.edit
        cabo = client_for(self.cabo1)
        self.assertEqual(cabo.get(f"/painel/dashboards/{self.private_cabo1.pk}/editar/").status_code, 403)
        self.assertEqual(cabo.get(f"/painel/dashboards/{self.default.pk}/editar/").status_code, 403)

    def test_edit_page_shows_sharing_options_only_to_admin(self):
        admin_page = client_for(self.admin).get(f"/painel/dashboards/{self.default.pk}/editar/")
        self.assertContains(admin_page, "Padrão da campanha")
        self.assertContains(admin_page, "Compartilhar com a equipe")
        coord_page = client_for(self.coord1).get(f"/painel/dashboards/{self.private_coord1.pk}/editar/")
        self.assertNotContains(coord_page, "Compartilhar com a equipe")
        self.assertContains(coord_page, "Este dashboard é seu")

    def test_super_admin_has_no_access_to_the_campaign_panel(self):
        client = client_for(self.superuser)
        self.assertEqual(client.get("/painel/").status_code, 302)
        self.assertEqual(client.get("/painel/dashboards/").status_code, 302)
        response = post_json(client, DATA_URL, {"widgets": []})
        self.assertEqual(response.status_code, 403)

    def test_user_without_dashboard_view_is_redirected_home_and_blocked_elsewhere(self):
        RolePermission.objects.filter(campaign=self.a, role=Role.CABO, module="dashboard").update(can_view=False)
        client = client_for(self.cabo1)
        response = client.get("/painel/")
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(response["Location"], "/painel/")
        self.assertTrue(response["Location"].startswith("/painel/"))
        self.assertEqual(client.get("/painel/dashboards/").status_code, 403)
        self.assertEqual(client.get(f"/painel/dashboards/{self.default.pk}/").status_code, 403)
        self.assertEqual(post_json(client, DATA_URL, {"widgets": []}).status_code, 403)


class HomeTests(ViewBase):
    def test_home_shows_greeting_ballot_name_and_default_dashboard(self):
        response = client_for(self.admin).get("/painel/")
        self.assertContains(response, "Olá, Maria!")
        self.assertContains(response, "Alfa")
        self.assertEqual(response.context["dashboard"].pk, self.default.pk)
        self.assertTrue(response.context["is_home"])
        self.assertNotContains(response, "Mostrando dados da sua rede")

    def test_network_hint_for_coordinator_and_cabo(self):
        for user in (self.coord1, self.cabo1):
            self.assertContains(client_for(user).get("/painel/"), "Mostrando dados da sua rede")

    def test_personal_default_wins_over_campaign_default(self):
        Dashboard.objects.filter(pk=self.private_coord1.pk).update(is_default=True)
        response = client_for(self.coord1).get("/painel/")
        self.assertEqual(response.context["dashboard"].pk, self.private_coord1.pk)
        # os demais continuam no padrão da campanha
        self.assertEqual(client_for(self.coord2).get("/painel/").context["dashboard"].pk, self.default.pk)

    def test_falls_back_to_first_visible_when_there_is_no_default(self):
        Dashboard.objects.filter(campaign=self.a).update(is_default=False)
        response = client_for(self.cabo2).get("/painel/")
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context["dashboard"])
        self.assertTrue(response.context["dashboard"].shared)

    def test_selector_lists_only_visible_dashboards(self):
        response = client_for(self.coord1).get("/painel/")
        names = {d.name for d in response.context["dashboards"]}
        self.assertIn("Painel do Carlos", names)
        self.assertIn("Visão geral", names)
        self.assertNotIn("Painel da Ana", names)
        self.assertNotIn("Segredo da Beta", names)
        self.assertNotContains(response, "Segredo da Beta")

    def test_personalize_button_depends_on_permission(self):
        self.assertContains(client_for(self.admin).get("/painel/"), "Personalizar")  # link para editar
        response = client_for(self.coord1).get("/painel/")  # compartilhado: cria cópia própria
        self.assertTrue(response.context["can_personalize"])
        self.assertContains(response, f"/painel/dashboards/{self.default.pk}/duplicar/")
        response = client_for(self.cabo1).get("/painel/")
        self.assertFalse(response.context["can_edit"])
        self.assertFalse(response.context["can_personalize"])
        self.assertNotContains(response, "Personalizar")

    def test_campaign_without_dashboards_admin_sees_create_defaults(self):
        Dashboard.objects.filter(campaign=self.a).delete()
        response = client_for(self.admin).get("/painel/")
        self.assertContains(response, "Criar dashboards padrão")
        self.assertTemplateUsed(response, "dashboards/home_empty.html")

    def test_admin_who_only_sees_foreign_private_dashboards_is_not_offered_defaults(self):
        Dashboard.objects.filter(campaign=self.a, owner__isnull=True).delete()  # sobram só os privados de outras pessoas
        for url in ("/painel/", "/painel/dashboards/"):
            response = client_for(self.admin).get(url)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "Criar dashboards padrão")
            self.assertContains(response, "Novo dashboard")

    def test_campaign_without_dashboards_others_see_read_only_preview_not_persisted(self):
        Dashboard.objects.filter(campaign=self.a).delete()
        for user in (self.coord1, self.cabo1):
            response = client_for(user).get("/painel/")
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.context["dashboard"])
            self.assertEqual(response.context["preview"]["name"], "Visão geral")
            self.assertEqual(len(response.context["widgets"]), len(DASHBOARD_PRESETS["visao_geral"]["widgets"]))
            self.assertContains(response, "Modelo de demonstração")
            self.assertNotContains(response, "Personalizar")
        self.assertEqual(Dashboard.objects.filter(campaign=self.a).count(), 0)

    def test_create_defaults_creates_four_with_one_campaign_default(self):
        Dashboard.objects.filter(campaign=self.a).delete()
        client = client_for(self.admin)
        response = client.post("/painel/dashboards/padroes/")
        self.assertRedirects(response, "/painel/", fetch_redirect_response=False)
        dashboards = Dashboard.objects.filter(campaign=self.a)
        self.assertEqual(dashboards.count(), 4)
        self.assertEqual(dashboards.filter(is_default=True, shared=True, owner__isnull=True).count(), 1)
        self.assertIn("dashboard.create", self.audit_actions())
        # segundo clique não duplica
        client.post("/painel/dashboards/padroes/")
        self.assertEqual(Dashboard.objects.filter(campaign=self.a).count(), 4)

    def test_create_defaults_does_nothing_when_campaign_already_has_dashboards(self):
        before = Dashboard.objects.filter(campaign=self.a).count()
        client_for(self.admin).post("/painel/dashboards/padroes/")
        self.assertEqual(Dashboard.objects.filter(campaign=self.a).count(), before)

    def test_create_defaults_is_admin_only_and_post_only(self):
        Dashboard.objects.filter(campaign=self.a).delete()
        self.assertEqual(client_for(self.coord1).post("/painel/dashboards/padroes/").status_code, 403)
        self.assertEqual(client_for(self.cabo1).post("/painel/dashboards/padroes/").status_code, 403)
        self.assertEqual(client_for(self.admin).get("/painel/dashboards/padroes/").status_code, 405)
        self.assertEqual(Dashboard.objects.filter(campaign=self.a).count(), 0)

    def test_create_defaults_only_touches_own_campaign(self):
        Dashboard.objects.filter(campaign=self.a).delete()
        client_for(self.admin).post("/painel/dashboards/padroes/")
        self.assertEqual(Dashboard.objects.filter(campaign=self.b).count(), 5)  # 4 + o privado criado no setup


class ListAndDetailTests(ViewBase):
    def test_list_shows_only_visible_dashboards(self):
        response = client_for(self.coord1).get("/painel/dashboards/")
        names = {d.name for d in response.context["dashboards"]}
        self.assertEqual(names, {"Visão geral", "Desempenho da equipe", "Territorial", "Comunicação (WhatsApp)", "Painel do Carlos"})
        self.assertContains(response, "Painel do Carlos")
        self.assertNotContains(response, "Painel da Ana")
        self.assertNotContains(response, "Segredo da Beta")

    def test_list_badges_and_actions_for_admin(self):
        response = client_for(self.admin).get("/painel/dashboards/")
        self.assertContains(response, "Padrão da campanha")
        self.assertContains(response, "Compartilhado")
        self.assertContains(response, "Excluir")
        self.assertContains(response, "Novo dashboard")
        self.assertContains(response, 'data-confirm="Excluir o dashboard')

    def test_list_actions_for_coordinator_and_cabo(self):
        response = client_for(self.coord1).get("/painel/dashboards/")
        by_name = {d.name: d for d in response.context["dashboards"]}
        self.assertFalse(by_name["Visão geral"].can_edit)
        self.assertFalse(by_name["Visão geral"].can_delete)
        self.assertTrue(by_name["Visão geral"].can_duplicate)
        self.assertTrue(by_name["Painel do Carlos"].can_edit)
        self.assertTrue(by_name["Painel do Carlos"].can_delete)
        response = client_for(self.cabo1).get("/painel/dashboards/")
        self.assertNotContains(response, "Novo dashboard")
        self.assertNotContains(response, "Excluir")
        self.assertNotContains(response, "Duplicar")

    def test_detail_of_shared_dashboard_for_everyone_with_view(self):
        for user in (self.admin, self.coord1, self.cabo1, self.cabo2):
            response = client_for(user).get(f"/painel/dashboards/{self.shared_team.pk}/")
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Desempenho da equipe")

    def test_private_dashboard_is_only_visible_to_its_owner(self):
        url = f"/painel/dashboards/{self.private_coord1.pk}/"
        self.assertEqual(client_for(self.coord1).get(url).status_code, 200)
        for user in (self.admin, self.coord2, self.cabo1, self.cabo2):
            self.assertEqual(client_for(user).get(url).status_code, 404, user.email)
            self.assertEqual(client_for(user).get(url + "editar/").status_code, 404, user.email)

    def test_other_campaign_dashboards_are_not_found(self):
        client = client_for(self.admin)
        for dash in (self.beta_default, self.beta_private):
            self.assertEqual(client.get(f"/painel/dashboards/{dash.pk}/").status_code, 404)
            self.assertEqual(client.get(f"/painel/dashboards/{dash.pk}/editar/").status_code, 404)
        self.assertEqual(client.get(f"/painel/dashboards/{uuid.uuid4()}/").status_code, 404)
        self.assertEqual(client.get("/painel/dashboards/nao-e-uuid/").status_code, 404)

    def test_detail_config_json_has_widgets_catalog_and_urls(self):
        response = client_for(self.admin).get(f"/painel/dashboards/{self.default.pk}/")
        config = response.context["dash_config"]
        self.assertEqual(config["dataUrl"], DATA_URL)
        self.assertFalse(config["editable"])
        self.assertEqual([w["id"] for w in config["widgets"]], [w["id"] for w in preset_widgets("visao_geral")])
        self.assertTrue(any(c["type"] == "ranking_members" for c in config["catalog"]))

    def test_catalog_marks_unavailable_widgets_for_user_without_permission(self):
        config = client_for(self.cabo1).get("/painel/").context["dash_config"]
        by_type = {c["type"]: c for c in config["catalog"]}
        self.assertFalse(by_type["broadcasts"]["available"])  # cabo não tem disparos.view
        self.assertTrue(by_type["recent_voters"]["available"])

    def test_names_are_escaped_in_pages(self):
        Dashboard.objects.filter(pk=self.private_coord1.pk).update(
            name='<script>alert("x")</script>', description="<img src=x onerror=alert(1)>"
        )
        client = client_for(self.coord1)
        for url in ("/painel/dashboards/", f"/painel/dashboards/{self.private_coord1.pk}/", f"/painel/dashboards/{self.private_coord1.pk}/editar/"):
            content = client.get(url).content.decode()
            self.assertNotIn('<script>alert("x")</script>', content, url)
            self.assertNotIn("<img src=x onerror=alert(1)>", content, url)

    def test_note_text_cannot_break_out_of_the_json_script(self):
        evil = "</script><script>alert(1)</script>"
        Dashboard.objects.filter(pk=self.private_coord1.pk).update(widgets=[widget("n1", "note", "full", text=evil)])
        content = client_for(self.coord1).get(f"/painel/dashboards/{self.private_coord1.pk}/").content.decode()
        self.assertNotIn(evil, content)
        self.assertIn("\\u003C/script\\u003E", content)


class CreateTests(ViewBase):
    def test_create_from_each_preset(self):
        client = client_for(self.coord1)
        for key, preset in DASHBOARD_PRESETS.items():
            response = client.post("/painel/dashboards/novo/", {"name": f"Meu {key}", "description": "teste", "preset": key})
            created = Dashboard.objects.get(campaign=self.a, name=f"Meu {key}")
            self.assertRedirects(response, f"/painel/dashboards/{created.pk}/editar/", fetch_redirect_response=False)
            self.assertEqual(created.owner_id, self.coord1.pk)
            self.assertFalse(created.shared)
            self.assertFalse(created.is_default)
            self.assertEqual(len(created.widgets), len(preset["widgets"]))
        self.assertEqual(self.audit_actions().count("dashboard.create"), len(DASHBOARD_PRESETS))

    def test_create_blank(self):
        client_for(self.coord1).post("/painel/dashboards/novo/", {"name": "Em branco", "preset": "blank"})
        self.assertEqual(Dashboard.objects.get(name="Em branco").widgets, [])

    def test_create_validation_errors(self):
        client = client_for(self.coord1)
        response = client.post("/painel/dashboards/novo/", {"name": "A", "preset": "blank"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Dashboard.objects.filter(name="A").exists())
        response = client.post("/painel/dashboards/novo/", {"name": "Painel", "preset": "hackeado"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Escolha um ponto de partida válido")
        self.assertFalse(Dashboard.objects.filter(name="Painel").exists())

    def test_create_requires_permission_and_post_creates_nothing_for_cabo(self):
        response = client_for(self.cabo1).post("/painel/dashboards/novo/", {"name": "Invasor", "preset": "blank"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Dashboard.objects.filter(name="Invasor").exists())

    def test_admin_creates_private_dashboard_too(self):
        client_for(self.admin).post("/painel/dashboards/novo/", {"name": "Do admin", "preset": "equipe"})
        created = Dashboard.objects.get(name="Do admin")
        self.assertEqual(created.owner_id, self.admin.pk)
        self.assertFalse(created.shared)

    def test_limit_of_own_dashboards(self):
        Dashboard.objects.bulk_create(
            [Dashboard(campaign=self.a, owner=self.coord2, name=f"D{i}", widgets=[]) for i in range(MAX_OWN_DASHBOARDS)]
        )
        response = client_for(self.coord2).post("/painel/dashboards/novo/", {"name": "Mais um", "preset": "blank"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Você já tem {MAX_OWN_DASHBOARDS} dashboards")
        self.assertFalse(Dashboard.objects.filter(name="Mais um").exists())


class DuplicateAndDefaultTests(ViewBase):
    def test_duplicate_shared_dashboard_makes_private_copy(self):
        client = client_for(self.coord1)
        response = client.post(f"/painel/dashboards/{self.default.pk}/duplicar/", {"then": "edit"})
        copy_ = Dashboard.objects.get(owner=self.coord1, name="Cópia de Visão geral")
        self.assertRedirects(response, f"/painel/dashboards/{copy_.pk}/editar/", fetch_redirect_response=False)
        self.assertFalse(copy_.shared)
        self.assertFalse(copy_.is_default)
        self.assertEqual(copy_.widgets, self.default.widgets)
        self.assertIsNot(copy_.pk, self.default.pk)
        self.assertIn("dashboard.create", self.audit_actions())

    def test_duplicate_from_list_goes_back_to_list(self):
        response = client_for(self.coord1).post(f"/painel/dashboards/{self.shared_team.pk}/duplicar/")
        self.assertRedirects(response, "/painel/dashboards/", fetch_redirect_response=False)

    def test_duplicate_requires_create_permission_visibility_and_post(self):
        self.assertEqual(client_for(self.cabo1).post(f"/painel/dashboards/{self.default.pk}/duplicar/").status_code, 403)
        self.assertEqual(client_for(self.coord1).post(f"/painel/dashboards/{self.private_cabo1.pk}/duplicar/").status_code, 404)
        self.assertEqual(client_for(self.admin).post(f"/painel/dashboards/{self.beta_default.pk}/duplicar/").status_code, 404)
        self.assertEqual(client_for(self.coord1).get(f"/painel/dashboards/{self.default.pk}/duplicar/").status_code, 405)

    def test_toggle_my_default_is_exclusive_per_owner(self):
        second = Dashboard.objects.create(campaign=self.a, owner=self.coord1, name="Segundo", widgets=[])
        client = client_for(self.coord1)
        client.post(f"/painel/dashboards/{self.private_coord1.pk}/padrao/")
        self.private_coord1.refresh_from_db()
        self.assertTrue(self.private_coord1.is_default)
        client.post(f"/painel/dashboards/{second.pk}/padrao/")
        self.private_coord1.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(self.private_coord1.is_default)
        self.assertTrue(second.is_default)
        # alternar de novo remove
        client.post(f"/painel/dashboards/{second.pk}/padrao/")
        second.refresh_from_db()
        self.assertFalse(second.is_default)
        # o padrão da campanha nunca é afetado
        self.default.refresh_from_db()
        self.assertTrue(self.default.is_default)

    def test_toggle_default_denied_for_shared_or_foreign_dashboards(self):
        client = client_for(self.coord1)
        self.assertEqual(client.post(f"/painel/dashboards/{self.default.pk}/padrao/").status_code, 403)
        self.assertEqual(client.post(f"/painel/dashboards/{self.private_cabo1.pk}/padrao/").status_code, 404)
        self.assertEqual(client.get(f"/painel/dashboards/{self.private_coord1.pk}/padrao/").status_code, 405)

    def test_toggle_default_ignores_external_next(self):
        response = client_for(self.coord1).post(
            f"/painel/dashboards/{self.private_coord1.pk}/padrao/", {"next": "https://evil.example/x"}
        )
        self.assertRedirects(response, "/painel/dashboards/", fetch_redirect_response=False)
        response = client_for(self.coord1).post(f"/painel/dashboards/{self.private_coord1.pk}/padrao/", {"next": "/painel/"})
        self.assertRedirects(response, "/painel/", fetch_redirect_response=False)

    def test_cabo_can_set_own_default_when_dashboard_is_visible(self):
        response = client_for(self.cabo1).post(f"/painel/dashboards/{self.private_cabo1.pk}/padrao/")
        self.assertEqual(response.status_code, 302)
        self.private_cabo1.refresh_from_db()
        self.assertTrue(self.private_cabo1.is_default)


class DeleteTests(ViewBase):
    def test_owner_deletes_own_private_dashboard(self):
        response = client_for(self.coord1).post(f"/painel/dashboards/{self.private_coord1.pk}/excluir/")
        self.assertRedirects(response, "/painel/dashboards/", fetch_redirect_response=False)
        self.assertFalse(Dashboard.objects.filter(pk=self.private_coord1.pk).exists())
        self.assertIn("dashboard.delete", self.audit_actions())

    def test_admin_deletes_shared_dashboard(self):
        client_for(self.admin).post(f"/painel/dashboards/{self.shared_team.pk}/excluir/")
        self.assertFalse(Dashboard.objects.filter(pk=self.shared_team.pk).exists())

    def test_non_admin_cannot_delete_shared_dashboards(self):
        for user in (self.coord1, self.cabo1):
            response = client_for(user).post(f"/painel/dashboards/{self.shared_team.pk}/excluir/")
            self.assertEqual(response.status_code, 403, user.email)
        self.assertTrue(Dashboard.objects.filter(pk=self.shared_team.pk).exists())

    def test_cannot_delete_other_users_or_other_campaign_dashboards(self):
        self.assertEqual(client_for(self.coord2).post(f"/painel/dashboards/{self.private_coord1.pk}/excluir/").status_code, 404)
        self.assertEqual(client_for(self.admin).post(f"/painel/dashboards/{self.private_coord1.pk}/excluir/").status_code, 404)
        self.assertEqual(client_for(self.admin).post(f"/painel/dashboards/{self.beta_default.pk}/excluir/").status_code, 404)
        self.assertTrue(Dashboard.objects.filter(pk__in=[self.private_coord1.pk, self.beta_default.pk]).count() == 2)

    def test_cabo_without_delete_permission_cannot_delete_even_own(self):
        response = client_for(self.cabo1).post(f"/painel/dashboards/{self.private_cabo1.pk}/excluir/")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Dashboard.objects.filter(pk=self.private_cabo1.pk).exists())

    def test_delete_requires_post(self):
        self.assertEqual(client_for(self.coord1).get(f"/painel/dashboards/{self.private_coord1.pk}/excluir/").status_code, 405)
        self.assertTrue(Dashboard.objects.filter(pk=self.private_coord1.pk).exists())

    def test_csrf_is_enforced_on_state_changes(self):
        client = client_for(self.coord1, enforce_csrf_checks=True)
        self.assertEqual(client.post(f"/painel/dashboards/{self.private_coord1.pk}/excluir/").status_code, 403)
        self.assertEqual(client.post(f"/painel/dashboards/{self.private_coord1.pk}/padrao/").status_code, 403)
        self.assertEqual(client.post("/painel/dashboards/novo/", {"name": "Sem token", "preset": "blank"}).status_code, 403)
        response = post_json(client, f"/api/painel/dashboard/{self.private_coord1.pk}/salvar/", {"name": "x", "widgets": []})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Dashboard.objects.filter(pk=self.private_coord1.pk).exists())
        self.assertFalse(Dashboard.objects.filter(name="Sem token").exists())


class SaveTests(ViewBase):
    def save_url(self, dashboard):
        return f"/api/painel/dashboard/{dashboard.pk}/salvar/"

    def payload(self, **extra):
        body = {"name": "Painel novo", "description": "Descrição", "widgets": [widget("k1", "kpi_total"), widget("r1", "ranking_members", "full", period=7, limit=5)]}
        body.update(extra)
        return body

    def test_owner_saves_name_description_and_widgets(self):
        response = post_json(client_for(self.coord1), self.save_url(self.private_coord1), self.payload())
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["message"], "Dashboard salvo.")
        self.assertIsNone(data["redirect"])
        self.private_coord1.refresh_from_db()
        self.assertEqual(self.private_coord1.name, "Painel novo")
        self.assertEqual(self.private_coord1.description, "Descrição")
        self.assertEqual([w["id"] for w in self.private_coord1.widgets], ["k1", "r1"])
        self.assertEqual(self.private_coord1.widgets[1]["config"], {"period": 7, "limit": 5})
        self.assertIn("dashboard.update", self.audit_actions())

    def test_audit_details_have_no_widget_content(self):
        post_json(client_for(self.coord1), self.save_url(self.private_coord1), self.payload(widgets=[widget("n1", "note", "full", text="telefone 11999998888")]))
        log = AuditLog.objects.filter(action="dashboard.update", campaign=self.a).first()
        self.assertNotIn("11999998888", json.dumps(log.details))

    def test_widgets_are_validated_on_the_server(self):
        client = client_for(self.coord1)
        url = self.save_url(self.private_coord1)
        bad_payloads = [
            [widget("x", "tipo_inexistente")],
            [widget("x", "kpi_total", "gigante")],
            [widget("x", "timeline", "lg", period=13)],
            [widget("x"), widget("x")],
            [widget(f"w{i}") for i in range(31)],
            "não é lista",
            [{"id": "<b>", "type": "kpi_total", "size": "sm", "config": {}}],
        ]
        for widgets in bad_payloads:
            response = post_json(client, url, self.payload(widgets=widgets))
            self.assertEqual(response.status_code, 400, widgets)
            self.assertIn("error", response.json())
        self.private_coord1.refresh_from_db()
        self.assertEqual(self.private_coord1.name, "Painel do Carlos")  # nada foi alterado

    def test_name_and_json_body_are_validated(self):
        client = client_for(self.coord1)
        url = self.save_url(self.private_coord1)
        self.assertEqual(post_json(client, url, self.payload(name="")).status_code, 400)
        self.assertEqual(post_json(client, url, self.payload(name="A")).status_code, 400)
        self.assertEqual(post_json(client, url, self.payload(name="x" * 81)).status_code, 400)
        self.assertEqual(client.post(url, data="isto não é json", content_type="application/json").status_code, 400)
        self.assertEqual(client.post(url, data="[1,2]", content_type="application/json").status_code, 400)

    def test_save_filters_out_of_scope_team_ids(self):
        out_of_scope = str(self.cabo2.pk)  # cabo da rede da outra coordenadora
        foreign = str(self.cabo_b.pk)  # outra campanha
        mine = str(self.cabo1.pk)
        widgets = [widget("k1", "kpi_total", filters={"registered_by_ids": [out_of_scope, foreign, mine], "genders": ["F"]})]
        response = post_json(client_for(self.coord1), self.save_url(self.private_coord1), self.payload(widgets=widgets))
        self.assertEqual(response.status_code, 200)
        self.private_coord1.refresh_from_db()
        self.assertEqual(self.private_coord1.widgets[0]["config"]["filters"], {"registered_by_ids": [mine], "genders": ["F"]})

    def test_save_drops_filters_that_only_contained_foreign_ids(self):
        widgets = [widget("k1", "kpi_total", filters={"coordinator_ids": [str(self.coord2.pk)]})]
        post_json(client_for(self.coord1), self.save_url(self.private_coord1), self.payload(widgets=widgets))
        self.private_coord1.refresh_from_db()
        self.assertNotIn("filters", self.private_coord1.widgets[0]["config"])

    def test_non_admin_cannot_share_or_set_campaign_default(self):
        response = post_json(
            client_for(self.coord1), self.save_url(self.private_coord1), self.payload(shared=True, campaign_default=True)
        )
        self.assertEqual(response.status_code, 200)
        self.private_coord1.refresh_from_db()
        self.assertFalse(self.private_coord1.shared)
        self.assertFalse(self.private_coord1.is_default)
        self.default.refresh_from_db()
        self.assertTrue(self.default.is_default)

    def test_non_admin_cannot_edit_shared_dashboards(self):
        response = post_json(client_for(self.coord1), self.save_url(self.default), self.payload())
        self.assertEqual(response.status_code, 403)
        self.default.refresh_from_db()
        self.assertEqual(self.default.name, "Visão geral")

    def test_cannot_save_someone_elses_or_other_campaigns_dashboard(self):
        self.assertEqual(post_json(client_for(self.coord2), self.save_url(self.private_coord1), self.payload()).status_code, 404)
        self.assertEqual(post_json(client_for(self.admin), self.save_url(self.private_coord1), self.payload()).status_code, 404)
        self.assertEqual(post_json(client_for(self.admin), self.save_url(self.beta_default), self.payload()).status_code, 404)
        self.private_coord1.refresh_from_db()
        self.beta_default.refresh_from_db()
        self.assertEqual(self.private_coord1.name, "Painel do Carlos")
        self.assertEqual(self.beta_default.name, "Visão geral")

    def test_cabo_without_edit_permission_cannot_save_own_dashboard(self):
        response = post_json(client_for(self.cabo1), self.save_url(self.private_cabo1), self.payload())
        self.assertEqual(response.status_code, 403)

    def test_admin_shares_and_sets_exactly_one_campaign_default(self):
        client = client_for(self.admin)
        response = post_json(client, self.save_url(self.shared_team), self.payload(shared=True, campaign_default=True))
        self.assertEqual(response.status_code, 200)
        defaults = Dashboard.objects.filter(campaign=self.a, shared=True, is_default=True)
        self.assertEqual(list(defaults.values_list("pk", flat=True)), [self.shared_team.pk])
        self.default.refresh_from_db()
        self.assertFalse(self.default.is_default)
        # a campanha B não é afetada
        self.assertTrue(Dashboard.objects.filter(campaign=self.b, shared=True, is_default=True).exists())
        # e a página inicial dos demais passa a usar o novo padrão
        self.assertEqual(client_for(self.cabo2).get("/painel/").context["dashboard"].pk, self.shared_team.pk)

    def test_admin_can_share_a_private_dashboard_with_the_team(self):
        mine = Dashboard.objects.create(campaign=self.a, owner=self.admin, name="Do admin", widgets=[])
        post_json(client_for(self.admin), self.save_url(mine), self.payload(shared=True))
        mine.refresh_from_db()
        self.assertTrue(mine.shared)
        self.assertFalse(mine.is_default)
        self.assertEqual(client_for(self.cabo1).get(f"/painel/dashboards/{mine.pk}/").status_code, 200)

    def test_campaign_default_implies_shared(self):
        mine = Dashboard.objects.create(campaign=self.a, owner=self.admin, name="Do admin", widgets=[])
        post_json(client_for(self.admin), self.save_url(mine), self.payload(shared=False, campaign_default=True))
        mine.refresh_from_db()
        self.assertTrue(mine.shared)
        self.assertTrue(mine.is_default)

    def test_admin_unsharing_template_makes_admin_the_owner(self):
        response = post_json(client_for(self.admin), self.save_url(self.shared_team), self.payload(shared=False))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["redirect"])
        self.shared_team.refresh_from_db()
        self.assertFalse(self.shared_team.shared)
        self.assertEqual(self.shared_team.owner_id, self.admin.pk)

    def test_save_requires_post(self):
        self.assertEqual(client_for(self.coord1).get(self.save_url(self.private_coord1)).status_code, 405)


class DataEndpointTests(ViewBase):
    def test_returns_data_keyed_by_widget_id_within_scope(self):
        widgets = [widget("t", "kpi_total"), widget("r", "ranking_members", "full", period=30)]
        cabo = post_json(client_for(self.cabo1), DATA_URL, {"widgets": widgets}).json()
        self.assertEqual(set(cabo), {"t", "r"})
        self.assertEqual(cabo["t"]["total"], 1)
        self.assertEqual([row["id"] for row in cabo["r"]["rows"]], [str(self.cabo1.pk)])
        admin = post_json(client_for(self.admin), DATA_URL, {"widgets": widgets}).json()
        self.assertEqual(admin["t"]["total"], 2)  # a campanha B nunca entra na conta
        self.assertNotIn(str(self.cabo_b.pk), json.dumps(admin))
        beta = post_json(client_for(self.admin_b), DATA_URL, {"widgets": widgets}).json()
        self.assertEqual(beta["t"]["total"], 1)

    def test_client_cannot_widen_scope_through_filters(self):
        widgets = [widget("t", "kpi_total", filters={"registered_by_ids": [str(self.cabo2.pk), str(self.cabo_b.pk)]})]
        data = post_json(client_for(self.cabo1), DATA_URL, {"widgets": widgets}).json()
        self.assertEqual(data["t"]["total"], 0)
        widgets = [widget("t", "by_neighborhood", filters={"cities": ["Segredo"]})]
        data = post_json(client_for(self.cabo1), DATA_URL, {"widgets": widgets}).json()
        self.assertEqual(data["t"]["rows"], [])

    def test_validates_the_widget_list(self):
        client = client_for(self.admin)
        self.assertEqual(post_json(client, DATA_URL, {"widgets": [widget("x", "inexistente")]}).status_code, 400)
        self.assertEqual(post_json(client, DATA_URL, {"widgets": "x"}).status_code, 400)
        self.assertEqual(post_json(client, DATA_URL, {}).status_code, 400)
        self.assertEqual(post_json(client, DATA_URL, [1]).status_code, 400)
        self.assertEqual(client.post(DATA_URL, data="{quebrado", content_type="application/json").status_code, 400)
        too_many = {"widgets": [widget(f"w{i}") for i in range(31)]}
        self.assertEqual(post_json(client, DATA_URL, too_many).status_code, 400)

    def test_empty_list_is_ok(self):
        response = post_json(client_for(self.admin), DATA_URL, {"widgets": []})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {})

    def test_forbidden_without_dashboard_view(self):
        RolePermission.objects.filter(campaign=self.a, role=Role.CABO, module="dashboard").update(can_view=False)
        response = post_json(client_for(self.cabo1), DATA_URL, {"widgets": [widget("t")]})
        self.assertEqual(response.status_code, 403)
        self.assertIn("error", response.json())

    def test_get_is_not_allowed(self):
        self.assertEqual(client_for(self.admin).get(DATA_URL).status_code, 405)

    def test_rate_limit(self):
        with mock.patch.object(views, "rate_limit", return_value=RateLimitResult(False, 0, 30)):
            response = post_json(client_for(self.admin), DATA_URL, {"widgets": [widget("t")]})
        self.assertEqual(response.status_code, 429)
        self.assertIn("error", response.json())

    def test_locked_widgets_return_locked_flags(self):
        widgets = [widget("b", "broadcasts", "full", period=30)]
        data = post_json(client_for(self.cabo1), DATA_URL, {"widgets": widgets}).json()
        self.assertTrue(data["b"]["locked"])

    def test_responses_are_not_cached(self):
        response = post_json(client_for(self.admin), DATA_URL, {"widgets": []})
        self.assertIn("no-store", response["Cache-Control"])


class FiltersFragmentTests(ViewBase):
    def test_fragment_contains_the_filter_panel_with_own_scope_options(self):
        response = client_for(self.cabo1).get(FILTERS_URL)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aplicar filtros")
        self.assertContains(response, "Centro")  # bairro do próprio cabo
        self.assertNotContains(response, "Taquaral")  # bairro de outro cabo
        self.assertNotContains(response, "Segredo")  # outra campanha
        self.assertNotContains(response, 'name="q"')

    def test_fragment_keeps_current_filters(self):
        response = client_for(self.admin).get(FILTERS_URL + "?bairro=Centro")
        self.assertContains(response, "1 filtro ativo")

    def test_fragment_requires_login_and_permission(self):
        self.assertEqual(Client().get(FILTERS_URL).status_code, 401)
        RolePermission.objects.filter(campaign=self.a, role=Role.CABO, module="dashboard").update(can_view=False)
        self.assertEqual(client_for(self.cabo1).get(FILTERS_URL).status_code, 403)


class AssetTests(ViewBase):
    def test_pages_load_the_module_scripts_and_they_exist(self):
        from django.conf import settings
        from pathlib import Path

        viewer = client_for(self.admin).get(f"/painel/dashboards/{self.default.pk}/").content.decode()
        editor = client_for(self.admin).get(f"/painel/dashboards/{self.default.pk}/editar/").content.decode()
        expected = {
            viewer: ["vendor/chart.umd.min.js", "js/dashboards/widgets.js", "js/dashboards/board.js", "js/dashboards/viewer.js"],
            editor: ["vendor/chart.umd.min.js", "vendor/Sortable.min.js", "js/dashboards/widgets.js", "js/dashboards/board.js", "js/dashboards/builder.js"],
        }
        for html, files in expected.items():
            for name in files:
                self.assertIn(name, html)
                self.assertTrue((Path(settings.BASE_DIR) / "static" / name).exists(), name)

    def test_every_catalog_icon_exists(self):
        from django.conf import settings
        from pathlib import Path

        from apps.dashboards.widgets import icon_names

        missing = [n for n in icon_names() if not (Path(settings.BASE_DIR) / "static" / "icons" / f"{n}.svg").exists()]
        self.assertEqual(missing, [])


class ReverseNamesTests(TestCase):
    def test_named_routes(self):
        pk = uuid.uuid4()
        self.assertEqual(reverse("dashboards:home"), "/painel/")
        self.assertEqual(reverse("dashboards:list"), "/painel/dashboards/")
        self.assertEqual(reverse("dashboards:detail", args=[pk]), f"/painel/dashboards/{pk}/")
        self.assertEqual(reverse("dashboards:edit", args=[pk]), f"/painel/dashboards/{pk}/editar/")
        self.assertEqual(reverse("dashboards:data"), DATA_URL)
        self.assertEqual(reverse("dashboards:save", args=[pk]), f"/api/painel/dashboard/{pk}/salvar/")

    def test_campaign_model_is_untouched_by_defaults(self):
        self.assertEqual(Campaign.objects.count(), 0)
