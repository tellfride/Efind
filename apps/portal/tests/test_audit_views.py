"""Auditoria da campanha: escopo por campanha e rede, filtros, paginação e exportação CSV."""

import datetime as dt

from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import User
from apps.auditlog.models import AuditLog

from .helpers import PASSWORD, Role, fast_hashing, grant, login, make_campaign, make_user

URL = "/painel/auditoria/"
EXPORT = "/painel/auditoria/exportar/"
BOM = "﻿"


def make_log(campaign, user, action="voter.create", when=None, **extra):
    log = AuditLog.objects.create(campaign=campaign, user=user, action=action, **extra)
    if when is not None:
        AuditLog.objects.filter(pk=log.pk).update(created_at=when)
        log.refresh_from_db()
    return log


@fast_hashing
class AuditBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.campaign = make_campaign("alfa")
        cls.other = make_campaign("beta")
        cls.admin = make_user(cls.campaign, "admin@a.com", Role.ADMIN, name="Ana Admin")
        cls.coord = make_user(cls.campaign, "coord@a.com", Role.COORDENADOR, parent=cls.admin, name="Caio Coord")
        cls.cabo = make_user(cls.campaign, "cabo@a.com", Role.CABO, parent=cls.coord, name="Duda Cabo")
        cls.coord2 = make_user(cls.campaign, "coord2@a.com", Role.COORDENADOR, parent=cls.admin, name="Eva Outra Rede")
        cls.admin_b = make_user(cls.other, "admin@b.com", Role.ADMIN, name="Bia Beta")
        cls.superuser = User.objects.create_superuser("super@x.com", PASSWORD, name="Suporte")

        cls.log_admin = make_log(cls.campaign, cls.admin, "settings.update", details={"fields": ["party"]}, ip="10.0.0.1", entity="Campaign")
        cls.log_coord = make_log(cls.campaign, cls.coord, "voter.export", details={"count": 7}, ip="10.0.0.2", entity="Voter")
        cls.log_cabo = make_log(cls.campaign, cls.cabo, "voter.create", ip="10.0.0.3", entity="Voter")
        cls.log_coord2 = make_log(cls.campaign, cls.coord2, "voter.delete", ip="10.0.0.4", entity="Voter")
        cls.log_system = make_log(cls.campaign, None, "voter.public_register", ip="10.0.0.5", entity="Voter")
        cls.log_super = make_log(cls.campaign, cls.superuser, "campaign.update", ip="10.0.0.6", entity="Campaign")
        # Linhas de OUTRA campanha (nunca podem aparecer)
        cls.foreign_1 = make_log(cls.other, cls.admin_b, "voter.export", details={"secret": "SEGREDO-DA-BETA"}, ip="203.0.113.9")
        cls.foreign_2 = make_log(cls.other, None, "broadcast.start", details={"nome": "DISPARO-BETA"}, ip="203.0.113.10")


class AuditAccessTests(AuditBase):
    def test_anonymous_redirected(self):
        for url in (URL, EXPORT):
            response = Client().get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertTrue(response["Location"].startswith("/login/?next="))

    def test_super_admin_has_no_campaign_audit_here(self):
        client = login("super@x.com")
        self.assertEqual(client.get(URL).status_code, 302)
        self.assertEqual(client.get(EXPORT).status_code, 302)

    def test_forbidden_without_permission(self):
        for email in ("coord@a.com", "cabo@a.com"):
            client = login(email)
            self.assertEqual(client.get(URL).status_code, 403, email)
            self.assertEqual(client.get(EXPORT).status_code, 403, email)

    def test_export_is_get_only(self):
        self.assertEqual(login("admin@a.com").post(EXPORT).status_code, 405)


class AuditListTests(AuditBase):
    def setUp(self):
        self.client = login("admin@a.com")

    def test_admin_sees_only_own_campaign_rows(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total"], 6)
        shown = {row["id"] for row in response.context["rows"]}
        self.assertEqual(shown, {str(l.pk) for l in (self.log_admin, self.log_coord, self.log_cabo, self.log_coord2, self.log_system, self.log_super)})
        self.assertNotContains(response, "SEGREDO-DA-BETA")
        self.assertNotContains(response, "DISPARO-BETA")
        self.assertNotContains(response, "203.0.113.9")
        self.assertNotContains(response, "Bia Beta")

    def test_other_admin_sees_only_theirs(self):
        response = login("admin@b.com").get(URL)
        self.assertEqual(response.context["total"], 2)
        self.assertContains(response, "SEGREDO-DA-BETA")
        self.assertNotContains(response, "10.0.0.1")
        self.assertNotContains(response, "Ana Admin")

    def test_rows_render_labels_ip_and_details(self):
        response = self.client.get(URL)
        self.assertContains(response, "Configurações atualizadas")
        self.assertContains(response, "Eleitores exportados")
        self.assertContains(response, "10.0.0.2")
        self.assertContains(response, "Ver detalhes")
        self.assertContains(response, "&quot;count&quot;: 7")  # JSON legível e escapado
        self.assertContains(response, "Suporte E-Find")  # ação do super admin identificada
        self.assertContains(response, "Sistema / eleitor")  # linha sem usuário
        self.assertContains(response, "Exportar CSV")
        self.assertContains(response, "LGPD")

    def test_filter_options_only_list_own_team(self):
        options = self.client.get(URL).context["options"]
        names = {u["name"] for u in options["users"]}
        self.assertEqual(names, {"Ana Admin", "Caio Coord", "Duda Cabo", "Eva Outra Rede"})
        self.assertNotIn("Bia Beta", names)

    def test_filter_by_user(self):
        response = self.client.get(URL, {"user": str(self.coord.pk)})
        self.assertEqual({r["id"] for r in response.context["rows"]}, {str(self.log_coord.pk)})
        self.assertEqual(response.context["total"], 1)

    def test_forged_user_from_other_campaign_is_ignored_not_widening(self):
        response = self.client.get(URL, {"user": str(self.admin_b.pk)})
        self.assertFalse(response.context["filters"].active)
        self.assertEqual(response.context["total"], 6)
        self.assertNotContains(response, "SEGREDO-DA-BETA")

    def test_filter_by_action(self):
        response = self.client.get(URL, {"action": "voter.export"})
        self.assertEqual(response.context["total"], 1)  # só a da própria campanha, nunca a da beta
        self.assertNotContains(response, "SEGREDO-DA-BETA")

    def test_malformed_filters_are_ignored(self):
        response = self.client.get(URL, {"user": "x'; DROP TABLE auditlog--", "action": "a b", "from": "ontem", "to": "99/99/9999", "page": "abc"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total"], 6)

    def test_filter_by_period_uses_sao_paulo_days(self):
        utc = dt.timezone.utc
        # 02:30 UTC de 02/03 = 23:30 de 01/03 em Brasília
        make_log(self.campaign, self.admin, "auth.login", when=dt.datetime(2026, 3, 2, 2, 30, tzinfo=utc))
        make_log(self.campaign, self.admin, "auth.logout", when=dt.datetime(2026, 3, 2, 4, 0, tzinfo=utc))
        response = self.client.get(URL, {"from": "2026-03-01", "to": "2026-03-01"})
        actions = {r["action"] for r in response.context["rows"]}
        self.assertEqual(actions, {"auth.login"})
        response = self.client.get(URL, {"from": "2026-03-02", "to": "2026-03-02"})
        self.assertEqual({r["action"] for r in response.context["rows"]}, {"auth.logout"})
        response = self.client.get(URL, {"from": "2026-03-02"})  # sem limite superior
        actions = {r["action"] for r in response.context["rows"]}
        self.assertIn("auth.logout", actions)
        self.assertNotIn("auth.login", actions)

    def test_empty_state_with_filters(self):
        response = self.client.get(URL, {"action": "dashboard.delete"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nenhum registro encontrado")
        self.assertContains(response, "Limpar filtros")

    def test_pagination_50_per_page(self):
        for i in range(120):
            make_log(self.campaign, self.admin, "auth.login", entity_id=str(i))
        total = 6 + 120
        page1 = self.client.get(URL)
        self.assertEqual(page1.context["total"], total)
        self.assertEqual(len(page1.context["rows"]), 50)
        page3 = self.client.get(URL, {"page": 3})
        self.assertEqual(len(page3.context["rows"]), total - 100)
        self.assertEqual(len(self.client.get(URL, {"page": 999}).context["rows"]), total - 100)  # última página
        self.assertContains(page1, "Página 1 de 3")

    def test_pagination_preserves_filters(self):
        for i in range(60):
            make_log(self.campaign, self.cabo, "auth.login")
        response = self.client.get(URL, {"user": str(self.cabo.pk)})
        self.assertContains(response, f"user={self.cabo.pk}")
        self.assertContains(response, "page=2")

    def test_newest_first(self):
        old = make_log(self.campaign, self.admin, "auth.logout", when=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc))
        ids = [r["id"] for r in self.client.get(URL).context["rows"]]
        self.assertEqual(ids[-1], str(old.pk))

    def test_query_count_does_not_grow_with_rows(self):
        for _ in range(30):
            make_log(self.campaign, self.cabo, "voter.create")
        with CaptureQueriesContext(connection) as small:
            self.client.get(URL, {"user": str(self.admin.pk)})
        with CaptureQueriesContext(connection) as large:
            self.client.get(URL)
        self.assertLessEqual(len(large), len(small) + 2)  # sem N+1 por linha


class AuditNetworkScopeTests(AuditBase):
    """Quem recebe auditoria.view sem ser ADMIN enxerga somente a própria rede."""

    def test_coordinator_sees_self_and_own_cabos_only(self):
        grant(self.campaign, Role.COORDENADOR, "auditoria", can_view=True)
        client = login("coord@a.com")
        response = client.get(URL)
        self.assertEqual(response.status_code, 200)
        shown = {r["id"] for r in response.context["rows"]}
        self.assertEqual(shown, {str(self.log_coord.pk), str(self.log_cabo.pk)})
        self.assertNotContains(response, "Eva Outra Rede")
        self.assertNotContains(response, "Ana Admin")
        self.assertContains(response, "somente as ações da sua própria rede")

    def test_coordinator_cannot_filter_other_networks(self):
        grant(self.campaign, Role.COORDENADOR, "auditoria", can_view=True)
        client = login("coord@a.com")
        response = client.get(URL, {"user": str(self.coord2.pk)})
        self.assertEqual(response.context["total"], 2)  # filtro inválido descartado, escopo mantido
        self.assertEqual({o["name"] for o in response.context["options"]["users"]}, {"Caio Coord", "Duda Cabo"})
        csv = client.get(EXPORT, {"user": str(self.coord2.pk)}).content.decode("utf-8")
        self.assertNotIn("10.0.0.4", csv)
        self.assertNotIn("10.0.0.1", csv)

    def test_cabo_with_permission_sees_only_own_rows(self):
        grant(self.campaign, Role.CABO, "auditoria", can_view=True)
        response = login("cabo@a.com").get(URL)
        self.assertEqual({r["id"] for r in response.context["rows"]}, {str(self.log_cabo.pk)})


class AuditExportTests(AuditBase):
    def setUp(self):
        self.client = login("admin@a.com")

    def csv(self, **params):
        response = self.client.get(EXPORT, params)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        self.assertIn("attachment; filename=\"auditoria_", response["Content-Disposition"])
        return response, response.content.decode("utf-8")

    def test_exports_only_own_campaign_with_header_and_bom(self):
        response, text = self.csv()
        self.assertTrue(text.startswith(BOM + "Data/hora (Brasília);Usuário;Papel;Ação;"))
        lines = [line for line in text.splitlines() if line]
        self.assertEqual(len(lines), 1 + 6)  # cabeçalho + 6 linhas da campanha (a exportação em si é gravada depois)
        self.assertIn("Ana Admin", text)
        self.assertIn("Suporte (suporte E-Find)", text)
        self.assertNotIn("SEGREDO-DA-BETA", text)
        self.assertNotIn("203.0.113", text)
        self.assertNotIn("Bia Beta", text)

    def test_export_honors_filters_and_filename(self):
        response, text = self.csv(action="voter.export", **{"from": "2020-01-01", "to": "2100-01-01"})
        self.assertIn("_2020-01-01_a_2100-01-01.csv", response["Content-Disposition"])
        lines = [line for line in text.splitlines() if line]
        self.assertEqual(len(lines), 2)
        self.assertIn("voter.export", lines[1])
        self.assertIn("10.0.0.2", lines[1])

    def test_export_filter_by_user(self):
        _, text = self.csv(user=str(self.cabo.pk))
        lines = [line for line in text.splitlines() if line]
        self.assertEqual(len(lines), 2)
        self.assertIn("Duda Cabo", lines[1])

    def test_export_period_with_no_rows(self):
        _, text = self.csv(**{"from": "2001-01-01", "to": "2001-01-02"})
        self.assertEqual(len([line for line in text.splitlines() if line]), 1)

    def test_export_is_itself_audited_without_personal_data(self):
        self.csv(action="voter.export")
        log = AuditLog.objects.filter(campaign=self.campaign, action="audit.export").get()
        self.assertEqual(log.user_id, self.admin.pk)
        self.assertEqual(log.details["filters"], {"action": "voter.export"})
        self.assertEqual(log.details["count"], 1)
        # a exportação seguinte inclui a anterior
        _, text = self.csv()
        self.assertIn("Auditoria exportada", text)

    def test_csv_formula_injection_is_neutralised(self):
        make_log(self.campaign, self.admin, "settings.update", entity='=HYPERLINK("http://x")', ip="10.9.9.9")
        _, text = self.csv()
        self.assertIn("'=HYPERLINK", text)
        self.assertNotIn(";=HYPERLINK", text)

    def test_export_details_column_is_json(self):
        _, text = self.csv(action="voter.export")
        self.assertIn('{""count"": 7}', text)

    def test_other_campaign_export_is_independent(self):
        text = login("admin@b.com").get(EXPORT).content.decode("utf-8")
        self.assertIn("SEGREDO-DA-BETA", text)
        self.assertNotIn("Ana Admin", text)
        self.assertNotIn("10.0.0.1", text)
