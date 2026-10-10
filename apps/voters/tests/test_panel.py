"""Painel de eleitores: escopo da lista, exportação, cadastro manual, detalhe, edição, descadastro, troca de
responsável e exclusão."""

import uuid

from django.utils import timezone

from apps.accounts.models import RolePermission
from apps.auditlog.models import AuditLog
from apps.core.constants import Role
from apps.messaging.models import Broadcast, BroadcastMessage
from apps.voters.models import Voter

from .helpers import VoterTestCase, make_user, make_voter

MANUAL = {
    "name": "carlos andrade",
    "phone": "(21) 99876-5432",
    "consent": "on",
    "support_level": "APOIADOR",
    "tags": "Saúde, Jovem",
    "notes": "Líder comunitário",
    "city": "Rio de Janeiro",
    "state": "RJ",
    "neighborhood": "centro",
}


class PanelBase(VoterTestCase):
    def setUp(self):
        super().setUp()
        self.v_cabo1 = make_voter(self.a, self.cabo1, name="Eleitor do Cabo 1", neighborhood="Centro", city="Campinas")
        self.v_cabo2 = make_voter(self.a, self.cabo2, name="Eleitor do Cabo 2", neighborhood="Cambuí", city="Campinas")
        self.v_coord1 = make_voter(self.a, self.coord1, name="Eleitor do Coord 1", neighborhood="Centro", city="Campinas")
        self.v_admin = make_voter(self.a, self.admin, name="Eleitor do Admin")
        self.v_other = make_voter(self.b, self.admin_b, name="Eleitor da Outra Campanha")


class AccessTests(PanelBase):
    PATHS = ["/painel/eleitores/", "/painel/eleitores/novo/", "/painel/eleitores/importar/", "/painel/meu-link/"]

    def test_anonymous_is_redirected_to_login(self):
        for path in self.PATHS + [
            "/painel/eleitores/exportar/",
            f"/painel/eleitores/{self.v_cabo1.pk}/",
            f"/painel/eleitores/{self.v_cabo1.pk}/editar/",
            "/painel/meu-link/cartaz/",
            "/painel/eleitores/importar/resultado/",
        ]:
            r = self.client.get(path)
            self.assertEqual(r.status_code, 302, path)
            self.assertTrue(r["Location"].startswith("/login/?next="), path)
        for path in [
            f"/painel/eleitores/{self.v_cabo1.pk}/excluir/",
            f"/painel/eleitores/{self.v_cabo1.pk}/descadastrar/",
            f"/painel/eleitores/{self.v_cabo1.pk}/responsavel/",
            "/painel/eleitores/localizar-novamente/",
        ]:
            r = self.client.post(path)
            self.assertEqual(r.status_code, 302, path)
            self.assertTrue(r["Location"].startswith("/login/"), path)
        self.assertEqual(self.client.post("/api/painel/eleitores/importar/previa/", "{}", content_type="application/json").status_code, 401)
        self.assertTrue(Voter.objects.filter(pk=self.v_cabo1.pk).exists())

    def test_smoke_pages_for_each_role(self):
        for user in (self.admin, self.coord1, self.cabo1):
            self.login(user)
            for path in self.PATHS + ["/painel/meu-link/cartaz/", f"/painel/eleitores/{self.v_cabo1.pk}/"]:
                self.assertEqual(self.client.get(path).status_code, 200, (user.role, path))
        self.login(self.admin)
        self.assertEqual(self.client.get(f"/painel/eleitores/{self.v_cabo1.pk}/editar/").status_code, 200)

    def test_super_admin_cannot_use_panel(self):
        from apps.accounts.models import User

        superuser = User.objects.create_superuser("super@x.com", "Senha@12345")
        self.login(superuser)
        for path in self.PATHS:
            self.assertEqual(self.client.get(path).status_code, 302, path)

    def test_missing_permissions_give_403(self):
        RolePermission.objects.filter(campaign=self.a, role=Role.CABO, module="eleitores").update(
            can_view=False, can_create=False, can_edit=False
        )
        RolePermission.objects.filter(campaign=self.a, role=Role.CABO, module="meu_link").update(can_view=False)
        self.login(self.cabo1)
        for path in self.PATHS + ["/painel/meu-link/cartaz/", "/painel/eleitores/exportar/", f"/painel/eleitores/{self.v_cabo1.pk}/"]:
            self.assertEqual(self.client.get(path).status_code, 403, path)

    def test_cabo_has_no_export_delete_or_admin_actions_by_default(self):
        self.login(self.cabo1)
        self.assertEqual(self.client.get("/painel/eleitores/exportar/").status_code, 403)
        self.assertEqual(self.client.post(f"/painel/eleitores/{self.v_cabo1.pk}/excluir/").status_code, 403)
        self.assertEqual(self.client.post(f"/painel/eleitores/{self.v_cabo1.pk}/responsavel/", {"registered_by": self.cabo2.pk}).status_code, 403)
        self.assertEqual(self.client.post("/painel/eleitores/localizar-novamente/").status_code, 403)
        self.assertTrue(Voter.objects.filter(pk=self.v_cabo1.pk).exists())
        r = self.client.get(f"/painel/eleitores/{self.v_cabo1.pk}/")
        self.assertNotContains(r, "Excluir definitivamente")
        self.assertNotContains(r, "Transferir")


class ListTests(PanelBase):
    def names(self, response):
        return {v.name for v in response.context["voters"]}

    def test_scope_per_role_and_campaign(self):
        self.login(self.admin)
        r = self.client.get("/painel/eleitores/")
        self.assertEqual(self.names(r), {"Eleitor do Cabo 1", "Eleitor do Cabo 2", "Eleitor do Coord 1", "Eleitor do Admin"})
        self.assertNotContains(r, "Outra Campanha")
        self.assertEqual(r.context["total"], 4)
        self.login(self.coord1)
        self.assertEqual(self.names(self.client.get("/painel/eleitores/")), {"Eleitor do Cabo 1", "Eleitor do Coord 1"})
        self.login(self.cabo1)
        r = self.client.get("/painel/eleitores/")
        self.assertEqual(self.names(r), {"Eleitor do Cabo 1"})
        self.assertNotContains(r, "Eleitor do Cabo 2")
        self.login(self.admin_b)
        self.assertEqual(self.names(self.client.get("/painel/eleitores/")), {"Eleitor da Outra Campanha"})

    def test_filters_never_widen_scope(self):
        self.login(self.cabo1)
        r = self.client.get(f"/painel/eleitores/?cabo={self.cabo2.pk}")
        self.assertEqual(r.context["total"], 0)
        r = self.client.get("/painel/eleitores/?bairro=Centro")
        self.assertEqual(self.names(r), {"Eleitor do Cabo 1"})
        self.login(self.admin)
        r = self.client.get("/painel/eleitores/?bairro=Centro&q=coord")
        self.assertEqual(self.names(r), {"Eleitor do Coord 1"})

    def test_summary_counts_messageable(self):
        Voter.objects.filter(pk=self.v_cabo1.pk).update(whatsapp_opt_in=True, consent_at=timezone.now())
        Voter.objects.filter(pk=self.v_cabo2.pk).update(whatsapp_opt_in=True, consent_at=timezone.now(), opt_out_at=timezone.now())
        self.login(self.admin)
        r = self.client.get("/painel/eleitores/")
        self.assertEqual((r.context["total"], r.context["messageable"]), (4, 1))
        self.assertContains(r, "apto a WhatsApp")
        self.assertContains(r, "Descadastrado")
        self.assertContains(r, "Sem autorização")

    def test_sorting_and_invalid_sort(self):
        self.login(self.admin)
        r = self.client.get("/painel/eleitores/?ordem=nome")
        names = [v.name for v in r.context["voters"]]
        self.assertEqual(names, sorted(names, key=str.lower))
        r = self.client.get("/painel/eleitores/?ordem=DROP")
        self.assertEqual(r.context["sort"], "recentes")

    def test_pagination_keeps_params_and_page_size(self):
        for i in range(30):
            make_voter(self.a, self.cabo1, neighborhood="Paginado")
        self.login(self.cabo1)
        r = self.client.get("/painel/eleitores/?bairro=Paginado")
        self.assertEqual(len(r.context["voters"]), 25)
        self.assertContains(r, "bairro=Paginado&amp;page=2")
        r = self.client.get("/painel/eleitores/?bairro=Paginado&page=2")
        self.assertEqual(len(r.context["voters"]), 5)
        self.assertEqual(self.client.get("/painel/eleitores/?page=999").status_code, 200)
        self.assertEqual(self.client.get("/painel/eleitores/?page=abc").status_code, 200)

    def test_pages_with_personal_data_are_not_cached(self):
        self.login(self.admin)
        for path in ("/painel/eleitores/", f"/painel/eleitores/{self.v_cabo1.pk}/", "/painel/eleitores/exportar/"):
            self.assertIn("no-store", self.client.get(path)["Cache-Control"], path)
        self.assertEqual(self.client.post(f"/painel/eleitores/{self.v_cabo1.pk}/").status_code, 405)
        self.assertEqual(self.client.post("/painel/eleitores/").status_code, 405)

    def test_empty_states(self):
        self.login(self.cabo2)
        Voter.objects.filter(registered_by=self.cabo2).delete()
        self.assertContains(self.client.get("/painel/eleitores/"), "Nenhum eleitor cadastrado ainda")
        self.assertContains(self.client.get("/painel/eleitores/?q=zzzz"), "Nenhum eleitor encontrado")

    def test_action_buttons_follow_permissions(self):
        self.login(self.admin)
        r = self.client.get("/painel/eleitores/")
        for text in ("Exportar CSV", "Importar", "Novo eleitor"):
            self.assertContains(r, text)
        self.login(self.cabo1)
        r = self.client.get("/painel/eleitores/")
        self.assertNotContains(r, "Exportar CSV")
        self.assertContains(r, "Novo eleitor")

    def test_retry_geo_button_only_for_admin(self):
        Voter.objects.filter(pk=self.v_cabo1.pk).update(geo_status="FAILED", cep="01310100")
        self.login(self.coord1)
        self.assertNotContains(self.client.get("/painel/eleitores/"), "Tentar localizar novamente")
        self.login(self.admin)
        self.assertContains(self.client.get("/painel/eleitores/"), "Tentar localizar novamente (1)")

    def test_retry_geo_post_is_campaign_scoped(self):
        Voter.objects.filter(pk__in=[self.v_cabo1.pk, self.v_other.pk]).update(geo_status="FAILED", cep="01310100", latitude=1, longitude=2)
        Voter.objects.filter(pk=self.v_admin.pk).update(geo_status="FAILED")  # sem endereço: não entra
        self.login(self.admin)
        r = self.client.post("/painel/eleitores/localizar-novamente/")
        self.assertRedirects(r, "/painel/eleitores/", fetch_redirect_response=False)
        self.v_cabo1.refresh_from_db()
        self.v_other.refresh_from_db()
        self.v_admin.refresh_from_db()
        self.assertEqual(self.v_cabo1.geo_status, "PENDING")
        self.assertIsNone(self.v_cabo1.latitude)
        self.assertEqual(self.v_other.geo_status, "FAILED")  # outra campanha intacta
        self.assertEqual(self.v_admin.geo_status, "FAILED")
        self.assertEqual(self.client.get("/painel/eleitores/localizar-novamente/").status_code, 405)


class ExportTests(PanelBase):
    def test_export_requires_permission(self):
        self.login(self.cabo1)
        self.assertEqual(self.client.get("/painel/eleitores/exportar/").status_code, 403)
        self.assertFalse(AuditLog.objects.filter(action="voter.export").exists())

    def test_export_csv_scope_filters_and_audit(self):
        self.login(self.coord1)
        r = self.client.get("/painel/eleitores/exportar/?bairro=Centro")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r["Content-Type"].startswith("text/csv"))
        self.assertIn("attachment; filename=\"eleitores-", r["Content-Disposition"])
        body = r.content.decode("utf-8-sig")
        self.assertIn("Eleitor do Cabo 1", body)
        self.assertIn("Eleitor do Coord 1", body)
        self.assertNotIn("Eleitor do Cabo 2", body)  # fora do escopo
        self.assertNotIn("Outra Campanha", body)
        self.assertIn("Nome;WhatsApp;E-mail", body)
        log = AuditLog.objects.get(action="voter.export")
        self.assertEqual(log.details["count"], 2)
        self.assertEqual(log.user_id, self.coord1.pk)

    def test_export_audit_hides_search_term(self):
        self.login(self.admin)
        self.client.get("/painel/eleitores/exportar/?q=Eleitor do Admin")
        log = AuditLog.objects.get(action="voter.export")
        self.assertNotIn("Admin", str(log.details))
        self.assertEqual(log.details["count"], 1)

    def test_export_protects_against_formula_injection(self):
        Voter.objects.filter(pk=self.v_cabo1.pk).update(name="=HYPERLINK(\"http://x\")", notes="+cmd|' /C calc'!A0")
        self.login(self.admin)
        body = self.client.get("/painel/eleitores/exportar/").content.decode("utf-8-sig")
        self.assertNotIn(";=HYPERLINK", body)
        self.assertNotIn("\n=HYPERLINK", body)
        self.assertIn("'=HYPERLINK", body)
        self.assertIn("'+cmd", body)

    def test_export_only_by_get(self):
        self.login(self.admin)
        self.assertEqual(self.client.post("/painel/eleitores/exportar/").status_code, 405)


class CreateTests(PanelBase):
    def test_form_renders_per_role(self):
        self.login(self.admin)
        r = self.client.get("/painel/eleitores/novo/")
        self.assertContains(r, "O eleitor autorizou o uso dos dados (LGPD)")
        self.assertContains(r, "O eleitor autorizou receber mensagens no WhatsApp")
        self.assertContains(r, "Cadastrado por")
        self.assertContains(r, 'data-cep-lookup')
        self.login(self.cabo1)
        self.assertNotContains(self.client.get("/painel/eleitores/novo/"), "Cadastrado por")

    def test_create_as_cabo_is_always_self(self):
        self.login(self.cabo1)
        r = self.client.post("/painel/eleitores/novo/", {**MANUAL, "registered_by": self.cabo2.pk})
        v = Voter.objects.get(phone="5521998765432")
        self.assertRedirects(r, f"/painel/eleitores/{v.pk}/", fetch_redirect_response=False)
        self.assertEqual(v.registered_by_id, self.cabo1.pk)  # ignora o campo enviado
        self.assertEqual(v.campaign_id, self.a.pk)
        self.assertEqual(v.name, "Carlos Andrade")
        self.assertEqual(v.source, "MANUAL")
        self.assertEqual(v.tags, ",saude,jovem,")
        self.assertEqual(v.support_level, "APOIADOR")
        self.assertIsNotNone(v.consent_at)
        self.assertFalse(v.whatsapp_opt_in)
        self.geocode_panel.assert_called_once_with(v.pk)
        log = AuditLog.objects.get(action="voter.create")
        self.assertEqual(log.details["voter_id"], str(v.pk))

    def test_consent_required(self):
        self.login(self.cabo1)
        data = {k: v for k, v in MANUAL.items() if k != "consent"}
        r = self.client.post("/painel/eleitores/novo/", data)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Confirme que o eleitor autorizou")
        self.assertFalse(Voter.objects.filter(phone="5521998765432").exists())

    def test_whatsapp_optin_checkbox(self):
        self.login(self.cabo1)
        self.client.post("/painel/eleitores/novo/", {**MANUAL, "whatsapp_opt_in": "on"})
        self.assertTrue(Voter.objects.get(phone="5521998765432").whatsapp_opt_in)

    def test_coordinator_can_pick_member_in_scope_only(self):
        self.login(self.coord1)
        r = self.client.post("/painel/eleitores/novo/", {**MANUAL, "registered_by": self.cabo2.pk})  # fora da rede
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Voter.objects.filter(phone="5521998765432").exists())
        r = self.client.post("/painel/eleitores/novo/", {**MANUAL, "registered_by": self.admin_b.pk})  # outra campanha
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Voter.objects.filter(phone="5521998765432").exists())
        self.client.post("/painel/eleitores/novo/", {**MANUAL, "registered_by": self.cabo1.pk})
        self.assertEqual(Voter.objects.get(phone="5521998765432").registered_by_id, self.cabo1.pk)

    def test_admin_default_is_self_and_can_pick_anyone_in_campaign(self):
        self.login(self.admin)
        self.client.post("/painel/eleitores/novo/", MANUAL)
        self.assertEqual(Voter.objects.get(phone="5521998765432").registered_by_id, self.admin.pk)
        r = self.client.post("/painel/eleitores/novo/", {**MANUAL, "phone": "21998765000", "registered_by": self.admin_b.pk})
        self.assertEqual(r.status_code, 200)
        self.client.post("/painel/eleitores/novo/", {**MANUAL, "phone": "21998765001", "registered_by": self.cabo2.pk})
        self.assertEqual(Voter.objects.get(phone="5521998765001").registered_by_id, self.cabo2.pk)

    def test_duplicate_phone_links_only_when_in_scope(self):
        self.login(self.cabo1)
        data = {**MANUAL, "phone": self.v_cabo1.phone}
        r = self.client.post("/painel/eleitores/novo/", data)
        self.assertContains(r, "Telefone já cadastrado na campanha")
        self.assertContains(r, f"/painel/eleitores/{self.v_cabo1.pk}/")  # no escopo → link
        r = self.client.post("/painel/eleitores/novo/", {**MANUAL, "phone": self.v_cabo2.phone})
        self.assertContains(r, "Telefone já cadastrado na campanha")
        self.assertNotContains(r, str(self.v_cabo2.pk))  # fora do escopo → mensagem genérica, sem link
        self.assertNotContains(r, "Eleitor do Cabo 2")

    def test_same_phone_in_other_campaign_is_allowed(self):
        self.login(self.admin)
        r = self.client.post("/painel/eleitores/novo/", {**MANUAL, "phone": self.v_other.phone})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Voter.objects.filter(phone=self.v_other.phone).count(), 2)

    def test_create_requires_post_csrf(self):
        from django.test import Client

        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.cabo1)
        self.assertEqual(strict.post("/painel/eleitores/novo/", MANUAL).status_code, 403)


class DetailAndEditTests(PanelBase):
    def test_detail_in_scope_and_404_outside(self):
        self.login(self.cabo1)
        r = self.client.get(f"/painel/eleitores/{self.v_cabo1.pk}/")
        self.assertContains(r, "Eleitor do Cabo 1")
        self.assertContains(r, "Cadastrado por")
        for other in (self.v_cabo2, self.v_other, self.v_coord1):
            self.assertEqual(self.client.get(f"/painel/eleitores/{other.pk}/").status_code, 404)
            self.assertEqual(self.client.get(f"/painel/eleitores/{other.pk}/editar/").status_code, 404)
        self.assertEqual(self.client.get(f"/painel/eleitores/{uuid.uuid4()}/").status_code, 404)
        self.assertEqual(self.client.get("/painel/eleitores/id-invalido/").status_code, 404)

    def test_coordinator_sees_cabos_but_not_siblings(self):
        self.login(self.coord1)
        self.assertEqual(self.client.get(f"/painel/eleitores/{self.v_cabo1.pk}/").status_code, 200)
        self.assertEqual(self.client.get(f"/painel/eleitores/{self.v_cabo2.pk}/").status_code, 404)

    def test_detail_shows_consent_and_messages_history(self):
        Voter.objects.filter(pk=self.v_cabo1.pk).update(
            consent_at=timezone.now(), consent_ip="203.0.113.7", consent_text="Texto aceito pelo eleitor", whatsapp_opt_in=True
        )
        broadcast = Broadcast.objects.create(campaign=self.a, name="Convite para o evento", created_by=self.admin)
        BroadcastMessage.objects.create(
            broadcast=broadcast, campaign=self.a, voter=self.v_cabo1, phone=self.v_cabo1.phone, rendered_body="CORPO SECRETO",
            status="DELIVERED", sent_at=timezone.now(),
        )
        self.login(self.admin)
        r = self.client.get(f"/painel/eleitores/{self.v_cabo1.pk}/")
        for text in ("203.0.113.7", "Texto aceito pelo eleitor", "Apto a WhatsApp", "Convite para o evento", "Entregue"):
            self.assertContains(r, text)
        self.assertNotContains(r, "CORPO SECRETO")

    def test_edit_updates_and_audits_without_pii(self):
        self.login(self.cabo1)
        url = f"/painel/eleitores/{self.v_cabo1.pk}/editar/"
        r = self.client.get(url)
        self.assertContains(r, 'value="Eleitor do Cabo 1"')
        r = self.client.post(url, {"name": "novo nome completo", "phone": "(11) 91111-2222", "support_level": "INDECISO", "tags": "a, b", "neighborhood": "Centro", "city": "Campinas"})
        self.assertRedirects(r, f"/painel/eleitores/{self.v_cabo1.pk}/", fetch_redirect_response=False)
        self.v_cabo1.refresh_from_db()
        self.assertEqual(self.v_cabo1.name, "Novo Nome Completo")
        self.assertEqual(self.v_cabo1.phone, "5511911112222")
        self.assertEqual(self.v_cabo1.support_level, "INDECISO")
        self.assertEqual(self.v_cabo1.registered_by_id, self.cabo1.pk)
        log = AuditLog.objects.get(action="voter.update")
        self.assertIn("name", log.details["fields"])
        self.assertNotIn("Novo Nome", str(log.details))
        self.geocode_panel.assert_not_called()  # endereço igual: não regeocodifica

    def test_edit_rechecks_phone_uniqueness(self):
        self.login(self.cabo1)
        r = self.client.post(f"/painel/eleitores/{self.v_cabo1.pk}/editar/", {"name": "Fulano de Tal", "phone": self.v_admin.phone})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Telefone já cadastrado na campanha")
        self.v_cabo1.refresh_from_db()
        self.assertNotEqual(self.v_cabo1.phone, self.v_admin.phone)
        # manter o próprio telefone é permitido
        r = self.client.post(f"/painel/eleitores/{self.v_cabo1.pk}/editar/", {"name": "Fulano de Tal", "phone": self.v_cabo1.phone})
        self.assertEqual(r.status_code, 302)

    def test_address_change_resets_geo_and_geocodes(self):
        Voter.objects.filter(pk=self.v_cabo1.pk).update(geo_status="OK", latitude=-22.9, longitude=-47.0)
        self.login(self.cabo1)
        self.client.post(
            f"/painel/eleitores/{self.v_cabo1.pk}/editar/",
            {"name": "Eleitor do Cabo 1", "phone": self.v_cabo1.phone, "neighborhood": "Cambuí", "city": "Campinas"},
        )
        self.v_cabo1.refresh_from_db()
        self.assertEqual(self.v_cabo1.geo_status, "PENDING")
        self.assertIsNone(self.v_cabo1.latitude)
        self.geocode_panel.assert_called_once_with(self.v_cabo1.pk)

    def test_edit_outside_scope_cannot_modify(self):
        self.login(self.cabo1)
        r = self.client.post(f"/painel/eleitores/{self.v_cabo2.pk}/editar/", {"name": "Invasor Teste", "phone": self.v_cabo2.phone})
        self.assertEqual(r.status_code, 404)
        self.v_cabo2.refresh_from_db()
        self.assertEqual(self.v_cabo2.name, "Eleitor do Cabo 2")

    def test_edit_requires_edit_permission(self):
        RolePermission.objects.filter(campaign=self.a, role=Role.CABO, module="eleitores").update(can_edit=False)
        self.login(self.cabo1)
        self.assertEqual(self.client.get(f"/painel/eleitores/{self.v_cabo1.pk}/editar/").status_code, 403)
        self.assertEqual(self.client.post(f"/painel/eleitores/{self.v_cabo1.pk}/descadastrar/").status_code, 403)
        r = self.client.get(f"/painel/eleitores/{self.v_cabo1.pk}/")
        self.assertNotContains(r, "Descadastrar do WhatsApp")


class ActionTests(PanelBase):
    def test_opt_out_is_one_way_and_audited(self):
        Voter.objects.filter(pk=self.v_cabo1.pk).update(whatsapp_opt_in=True, consent_at=timezone.now())
        self.login(self.cabo1)
        url = f"/painel/eleitores/{self.v_cabo1.pk}/descadastrar/"
        self.assertEqual(self.client.get(url).status_code, 405)
        r = self.client.post(url)
        self.assertRedirects(r, f"/painel/eleitores/{self.v_cabo1.pk}/", fetch_redirect_response=False)
        self.v_cabo1.refresh_from_db()
        self.assertIsNotNone(self.v_cabo1.opt_out_at)
        self.assertFalse(Voter.objects.filter(pk=self.v_cabo1.pk, opt_out_at__isnull=True, whatsapp_opt_in=True).exists())
        self.assertTrue(AuditLog.objects.filter(action="voter.opt_out").exists())
        page = self.client.get(f"/painel/eleitores/{self.v_cabo1.pk}/")
        self.assertContains(page, "Não é possível reativar pelo painel")
        self.assertNotContains(page, "Descadastrar do WhatsApp</button>")
        first = self.v_cabo1.opt_out_at
        self.client.post(url)
        self.v_cabo1.refresh_from_db()
        self.assertEqual(self.v_cabo1.opt_out_at, first)

    def test_opt_out_outside_scope_is_404(self):
        self.login(self.cabo1)
        self.assertEqual(self.client.post(f"/painel/eleitores/{self.v_cabo2.pk}/descadastrar/").status_code, 404)
        self.v_cabo2.refresh_from_db()
        self.assertIsNone(self.v_cabo2.opt_out_at)

    def test_change_registrar_admin_only_and_same_campaign(self):
        url = f"/painel/eleitores/{self.v_cabo1.pk}/responsavel/"
        self.login(self.coord1)
        self.assertEqual(self.client.post(url, {"registered_by": self.coord1.pk}).status_code, 403)
        self.login(self.admin)
        self.client.post(url, {"registered_by": self.admin_b.pk})  # outra campanha
        self.v_cabo1.refresh_from_db()
        self.assertEqual(self.v_cabo1.registered_by_id, self.cabo1.pk)
        self.client.post(url, {"registered_by": uuid.uuid4()})
        self.v_cabo1.refresh_from_db()
        self.assertEqual(self.v_cabo1.registered_by_id, self.cabo1.pk)
        r = self.client.post(url, {"registered_by": self.cabo2.pk})
        self.assertRedirects(r, f"/painel/eleitores/{self.v_cabo1.pk}/", fetch_redirect_response=False)
        self.v_cabo1.refresh_from_db()
        self.assertEqual(self.v_cabo1.registered_by_id, self.cabo2.pk)
        log = AuditLog.objects.get(action="voter.update", details__change="registered_by")
        self.assertEqual(log.details["to"], str(self.cabo2.pk))
        self.assertContains(self.client.get(f"/painel/eleitores/{self.v_cabo1.pk}/"), "Transferir")

    def test_change_registrar_requires_a_selection(self):
        self.login(self.admin)
        self.client.post(f"/painel/eleitores/{self.v_cabo1.pk}/responsavel/", {"registered_by": ""})
        self.v_cabo1.refresh_from_db()
        self.assertEqual(self.v_cabo1.registered_by_id, self.cabo1.pk)

    def test_change_registrar_rejects_inactive_member(self):
        inactive = make_user(self.a, "inativo@a.com", Role.CABO, parent=self.coord1, is_active=False)
        self.login(self.admin)
        self.client.post(f"/painel/eleitores/{self.v_cabo1.pk}/responsavel/", {"registered_by": inactive.pk})
        self.v_cabo1.refresh_from_db()
        self.assertEqual(self.v_cabo1.registered_by_id, self.cabo1.pk)

    def test_delete_is_hard_scoped_and_audited(self):
        RolePermission.objects.filter(campaign=self.a, role=Role.COORDENADOR, module="eleitores").update(can_delete=True)
        self.login(self.coord1)
        url = f"/painel/eleitores/{self.v_cabo1.pk}/excluir/"
        self.assertEqual(self.client.get(url).status_code, 405)
        # fora do escopo / outra campanha: 404 e nada é apagado
        self.assertEqual(self.client.post(f"/painel/eleitores/{self.v_cabo2.pk}/excluir/").status_code, 404)
        self.assertEqual(self.client.post(f"/painel/eleitores/{self.v_other.pk}/excluir/").status_code, 404)
        self.assertTrue(Voter.objects.filter(pk__in=[self.v_cabo2.pk, self.v_other.pk]).count() == 2)
        r = self.client.post(url)
        self.assertRedirects(r, "/painel/eleitores/", fetch_redirect_response=False)
        self.assertFalse(Voter.objects.filter(pk=self.v_cabo1.pk).exists())
        log = AuditLog.objects.get(action="voter.delete")
        self.assertEqual(log.details, {"voter_id": str(self.v_cabo1.pk)})

    def test_delete_keeps_broadcast_history_rows(self):
        broadcast = Broadcast.objects.create(campaign=self.a, name="Disparo", created_by=self.admin)
        msg = BroadcastMessage.objects.create(broadcast=broadcast, campaign=self.a, voter=self.v_cabo1, phone="5511900000000", rendered_body="x")
        self.login(self.admin)
        self.client.post(f"/painel/eleitores/{self.v_cabo1.pk}/excluir/")
        msg.refresh_from_db()
        self.assertIsNone(msg.voter_id)
