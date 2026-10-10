"""Dados dos widgets: escopo hierárquico, isolamento entre campanhas, permissões e formato JSON."""

import datetime as dt
import json
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import RolePermission
from apps.core.constants import Role
from apps.dashboards import data as dash_data
from apps.dashboards.data import DataContext, compute_dashboard_data, compute_widget_data
from apps.dashboards.presets import preset_widgets
from apps.dashboards.widgets import WIDGET_CATALOG, create_widget
from apps.messaging.models import Broadcast, BroadcastMessage

from .helpers import UTC, fast_hashing, make_campaign, make_user, make_voter

NOW = dt.datetime(2026, 10, 10, 15, 0, tzinfo=UTC)  # 12:00 em São Paulo
TODAY_NOON = dt.datetime(2026, 10, 10, 14, 0, tzinfo=UTC)


def days_ago(n, hour=14):
    return dt.datetime(2026, 10, 10, hour, 0, tzinfo=UTC) - dt.timedelta(days=n)


def widget(type_, id_="w", **config):
    return {"id": id_, "type": type_, "size": "md", "config": config}


@fast_hashing
class DataBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = make_campaign("alfa", voter_goal=1000)
        cls.b = make_campaign("beta", voter_goal=50)
        cls.admin = make_user(cls.a, "admin@a.com", Role.ADMIN)
        cls.coord1 = make_user(cls.a, "coord1@a.com", Role.COORDENADOR, parent=cls.admin, name="Carlos Coord", goal=100)
        cls.coord2 = make_user(cls.a, "coord2@a.com", Role.COORDENADOR, parent=cls.admin, name="Dora Coord")
        cls.cabo1 = make_user(cls.a, "cabo1@a.com", Role.CABO, parent=cls.coord1, name="Ana Cabo", goal=50)
        cls.cabo2 = make_user(cls.a, "cabo2@a.com", Role.CABO, parent=cls.coord2, name="Bia Cabo", goal=20)
        cls.cabo_idle = make_user(cls.a, "idle@a.com", Role.CABO, parent=cls.coord1, name="Zeca Parado")
        cls.admin_b = make_user(cls.b, "admin@b.com", Role.ADMIN)
        cls.cabo_b = make_user(cls.b, "cabo@b.com", Role.CABO, parent=cls.admin_b, name="Cabo da Beta", goal=10)

        # Campanha A — cabo1: hoje, há 5 dias e há 40 dias; cabo2: hoje e há 20 dias; coord1: há 3 dias
        cls.v1 = make_voter(cls.a, cls.cabo1, 1, TODAY_NOON, neighborhood="Centro", city="Campinas", gender="F",
                            support_level="APOIADOR", source="LINK", birth_date=dt.date(2000, 1, 1))  # fmt: skip
        cls.v2 = make_voter(cls.a, cls.cabo1, 2, days_ago(5), neighborhood="Centro", city="Campinas", gender="M",
                            support_level="INDECISO", source="QRCODE", birth_date=dt.date(1960, 5, 5))  # fmt: skip
        cls.v3 = make_voter(cls.a, cls.cabo1, 3, days_ago(40), neighborhood="Cambuí", city="Campinas", gender="F",
                            source="MANUAL")  # fmt: skip
        cls.v4 = make_voter(cls.a, cls.cabo2, 4, TODAY_NOON, neighborhood="Taquaral", city="Valinhos", gender="M",
                            support_level="OPOSITOR", source="LINK", birth_date=dt.date(1985, 7, 7))  # fmt: skip
        cls.v5 = make_voter(cls.a, cls.cabo2, 5, days_ago(20), neighborhood="Taquaral", city="Valinhos",
                            whatsapp_opt_in=True, consent_at=days_ago(20))  # fmt: skip
        cls.v6 = make_voter(cls.a, cls.coord1, 6, days_ago(3), neighborhood="Centro", city="Campinas", gender="F",
                            whatsapp_opt_in=True, consent_at=days_ago(3))  # fmt: skip
        # Campanha B (nunca pode aparecer para a A)
        for n in range(7, 10):
            make_voter(cls.b, cls.cabo_b, n, TODAY_NOON, neighborhood="Segredo", city="Outra Cidade")

    def run_widget(self, user, type_, **config):
        return compute_widget_data(user, widget(type_, **config), DataContext(user, now=NOW))


class ScopeTests(DataBase):
    def test_kpi_total_respects_hierarchy_and_campaign(self):
        self.assertEqual(self.run_widget(self.admin, "kpi_total")["total"], 6)
        self.assertEqual(self.run_widget(self.coord1, "kpi_total")["total"], 4)  # ele + cabo1 (cabo_idle sem cadastros)
        self.assertEqual(self.run_widget(self.coord2, "kpi_total")["total"], 2)
        self.assertEqual(self.run_widget(self.cabo1, "kpi_total")["total"], 3)
        self.assertEqual(self.run_widget(self.cabo_idle, "kpi_total")["total"], 0)
        self.assertEqual(self.run_widget(self.admin_b, "kpi_total")["total"], 3)

    def test_kpi_total_last_seven_days(self):
        self.assertEqual(self.run_widget(self.admin, "kpi_total")["last7"], 4)  # v1, v2, v4, v6

    def test_ranking_members_for_cabo_only_contains_himself(self):
        data = self.run_widget(self.cabo1, "ranking_members", period=30)
        self.assertEqual([r["id"] for r in data["rows"]], [str(self.cabo1.pk)])

    def test_ranking_members_for_coordinator_shows_his_network(self):
        data = self.run_widget(self.coord1, "ranking_members", period=30)
        ids = {r["id"] for r in data["rows"]}
        self.assertEqual(ids, {str(self.cabo1.pk), str(self.coord1.pk), str(self.cabo_idle.pk)})
        self.assertNotIn(str(self.cabo2.pk), ids)

    def test_ranking_members_for_admin_ordered_and_without_other_campaign(self):
        data = self.run_widget(self.admin, "ranking_members", period=30)
        rows = data["rows"]
        ids = [r["id"] for r in rows]
        self.assertNotIn(str(self.cabo_b.pk), ids)
        self.assertNotIn(str(self.admin.pk), ids)  # administrador sem cadastros fica fora
        # cabo1 e cabo2 têm 2 e 1 cadastros nos 30 dias; coord1 tem 1; o cabo parado entra com zero
        self.assertEqual(ids[0], str(self.cabo1.pk))
        self.assertEqual(rows[0]["in_period"], 2)
        self.assertEqual(rows[0]["total"], 3)
        self.assertEqual(rows[0]["goal_pct"], 6.0)
        self.assertEqual(rows[0]["coordinator_name"], "Carlos Coord")
        idle = next(r for r in rows if r["id"] == str(self.cabo_idle.pk))
        self.assertEqual((idle["total"], idle["in_period"], idle["last_at"]), (0, 0, None))
        self.assertEqual(data["period_total"], 5)  # v1, v2, v4, v5, v6 (v3 tem 40 dias)
        self.assertEqual(data["total"], 6)
        self.assertEqual(data["contributing"], 3)  # cabo1, cabo2 e coord1 cadastraram no período

    def test_ranking_members_period_changes_counts(self):
        week = self.run_widget(self.admin, "ranking_members", period=7)
        self.assertEqual(next(r for r in week["rows"] if r["id"] == str(self.cabo2.pk))["in_period"], 1)  # v4 de hoje
        year = self.run_widget(self.admin, "ranking_members", period=365)
        self.assertEqual(next(r for r in year["rows"] if r["id"] == str(self.cabo1.pk))["in_period"], 3)

    def test_ranking_filters_never_widen_scope(self):
        data = self.run_widget(self.cabo1, "ranking_members", period=30, filters={"registered_by_ids": [str(self.cabo2.pk)]})
        self.assertEqual(data["rows"], [])
        self.assertEqual(data["total"], 0)

    def test_ranking_coordinators(self):
        admin_data = self.run_widget(self.admin, "ranking_coordinators", period=30)
        self.assertTrue(admin_data["applicable"])
        by_name = {r["name"]: r for r in admin_data["rows"]}
        self.assertEqual(set(by_name), {"Carlos Coord", "Dora Coord"})
        self.assertEqual(by_name["Carlos Coord"]["total"], 4)  # próprio + cabo1
        self.assertEqual(by_name["Carlos Coord"]["own"], 1)
        self.assertEqual(by_name["Carlos Coord"]["cabos"], 2)
        self.assertEqual(by_name["Dora Coord"]["total"], 2)
        self.assertEqual(by_name["Carlos Coord"]["goal"], 100)
        self.assertEqual(admin_data["rows"][0]["name"], "Carlos Coord")
        coord_data = self.run_widget(self.coord2, "ranking_coordinators", period=30)
        self.assertEqual([r["name"] for r in coord_data["rows"]], ["Dora Coord"])
        cabo_data = self.run_widget(self.cabo1, "ranking_coordinators", period=30)
        self.assertFalse(cabo_data["applicable"])
        self.assertEqual(cabo_data["rows"], [])

    def test_territory_widgets_are_scoped(self):
        admin = self.run_widget(self.admin, "by_neighborhood", limit=10)
        labels = {r["label"]: r["count"] for r in admin["rows"]}
        self.assertEqual(labels, {"Centro": 3, "Taquaral": 2, "Cambuí": 1})
        self.assertNotIn("Segredo", labels)
        cabo = self.run_widget(self.cabo2, "by_neighborhood", limit=10)
        self.assertEqual({r["label"]: r["count"] for r in cabo["rows"]}, {"Taquaral": 2})
        cities = self.run_widget(self.coord1, "by_city", limit=10)
        self.assertEqual({r["label"]: r["count"] for r in cities["rows"]}, {"Campinas": 4})

    def test_by_neighborhood_limit_and_rest(self):
        data = self.run_widget(self.admin, "by_neighborhood", limit=3)
        self.assertEqual(len(data["rows"]), 3)
        data = self.run_widget(self.admin, "by_city", limit=3)
        self.assertEqual(data["others"], 0)

    def test_recent_voters_scope_and_order(self):
        data = self.run_widget(self.cabo1, "recent_voters", limit=5)
        self.assertFalse(data["locked"])
        self.assertEqual([r["name"] for r in data["rows"]], ["Eleitor 1", "Eleitor 2", "Eleitor 3"])
        self.assertEqual(data["rows"][0]["registered_by"], "Ana Cabo")
        self.assertTrue(data["rows"][0]["url"].startswith("/painel/eleitores/"))
        admin = self.run_widget(self.admin, "recent_voters", limit=20)
        self.assertEqual(len(admin["rows"]), 6)
        self.assertNotIn("Eleitor 7", [r["name"] for r in admin["rows"]])

    def test_recent_voters_locked_without_permission(self):
        RolePermission.objects.filter(campaign=self.a, role=Role.CABO, module="eleitores").update(can_view=False)
        data = self.run_widget(self.cabo1, "recent_voters", limit=5)
        self.assertTrue(data["locked"])
        self.assertEqual(data["rows"], [])

    def test_unknown_widget_type_is_rejected(self):
        with self.assertRaises(ValueError):
            compute_widget_data(self.admin, widget("hack"), DataContext(self.admin, now=NOW))


class KpiTests(DataBase):
    def test_today_and_yesterday(self):
        make_voter(self.a, self.cabo2, 20, days_ago(1))
        data = self.run_widget(self.admin, "kpi_today")
        self.assertEqual((data["today"], data["yesterday"]), (2, 1))
        self.assertEqual(self.run_widget(self.cabo1, "kpi_today")["today"], 1)

    def test_today_uses_sao_paulo_midnight(self):
        # 02:30 UTC de 10/10 = 23:30 de 09/10 em São Paulo → ainda é "ontem"
        make_voter(self.a, self.cabo1, 21, dt.datetime(2026, 10, 10, 2, 30, tzinfo=UTC))
        data = self.run_widget(self.cabo1, "kpi_today")
        self.assertEqual((data["today"], data["yesterday"]), (1, 1))

    def test_period_with_comparison_to_previous(self):
        data = self.run_widget(self.admin, "kpi_period", period=7)
        comparison = data["comparison"]
        self.assertEqual((comparison["current"], comparison["previous"]), (4, 0))
        self.assertIsNone(comparison["delta_pct"])
        data = self.run_widget(self.admin, "kpi_period", period=30)
        comparison = data["comparison"]
        self.assertEqual((comparison["current"], comparison["previous"]), (5, 1))  # v3 (40 dias) está no período anterior
        self.assertEqual(comparison["delta_pct"], 400.0)
        self.assertEqual(comparison["trend"], "up")

    def test_goal_admin_uses_campaign_goal(self):
        data = self.run_widget(self.admin, "kpi_goal")
        self.assertEqual((data["total"], data["goal"], data["source"]), (6, 1000, "campaign"))
        self.assertEqual(data["pct"], 0.6)

    def test_goal_non_admin_sums_goals_of_visible_team(self):
        data = self.run_widget(self.coord1, "kpi_goal")
        self.assertEqual((data["goal"], data["source"], data["members_with_goal"]), (150, "team", 2))  # 100 + 50
        self.assertEqual(data["total"], 4)
        cabo = self.run_widget(self.cabo2, "kpi_goal")
        self.assertEqual((cabo["goal"], cabo["total"], cabo["pct"]), (20, 2, 10.0))
        without = self.run_widget(self.cabo_idle, "kpi_goal")
        self.assertIsNone(without["goal"])
        self.assertIsNone(without["pct"])

    def test_goal_admin_without_campaign_goal(self):
        type(self.a).objects.filter(pk=self.a.pk).update(voter_goal=None)
        data = self.run_widget(self.admin, "kpi_goal")
        self.assertIsNone(data["goal"])

    def test_messageable(self):
        data = self.run_widget(self.admin, "kpi_messageable")
        self.assertEqual((data["messageable"], data["total"], data["pct"]), (2, 6, 33.3))
        make_voter(self.a, self.cabo1, 22, whatsapp_opt_in=True, consent_at=NOW, opt_out_at=NOW)  # descadastrado
        make_voter(self.a, self.cabo1, 23, whatsapp_opt_in=True)  # sem consentimento registrado
        self.assertEqual(self.run_widget(self.admin, "kpi_messageable")["messageable"], 2)
        self.assertEqual(self.run_widget(self.cabo1, "kpi_messageable")["messageable"], 0)

    def test_team(self):
        data = self.run_widget(self.admin, "kpi_team", period=30)
        self.assertEqual(data["active"], 6)  # admin, 2 coord, 3 cabos
        self.assertEqual(data["contributing"], 3)  # cabo1, cabo2 e coord1
        self.assertEqual(self.run_widget(self.cabo1, "kpi_team", period=30)["active"], 1)
        User = type(self.cabo1)
        User.objects.filter(pk=self.cabo2.pk).update(is_active=False)
        self.assertEqual(self.run_widget(self.admin, "kpi_team", period=30)["active"], 5)


class TimelineAndDistributionTests(DataBase):
    def test_timeline_fills_missing_days_with_zero(self):
        data = self.run_widget(self.admin, "timeline", period=30)
        points = data["points"]
        self.assertEqual(len(points), 30)
        self.assertEqual(points[0]["date"], "2026-09-11")
        self.assertEqual(points[-1]["date"], "2026-10-10")
        counts = {p["date"]: p["count"] for p in points}
        self.assertEqual(counts["2026-10-10"], 2)  # v1 e v4
        self.assertEqual(counts["2026-10-05"], 1)  # v2
        self.assertEqual(counts["2026-10-07"], 1)  # v6
        self.assertEqual(counts["2026-09-20"], 1)  # v5
        self.assertEqual(counts["2026-10-01"], 0)
        self.assertEqual(data["total"], 5)
        self.assertEqual(data["previous_total"], 1)

    def test_timeline_groups_by_sao_paulo_day(self):
        make_voter(self.a, self.cabo1, 30, dt.datetime(2026, 10, 9, 2, 30, tzinfo=UTC))  # 23:30 de 08/10 em SP
        make_voter(self.a, self.cabo1, 31, dt.datetime(2026, 10, 9, 3, 30, tzinfo=UTC))  # 00:30 de 09/10 em SP
        counts = {p["date"]: p["count"] for p in self.run_widget(self.cabo1, "timeline", period=7)["points"]}
        self.assertEqual(counts["2026-10-08"], 1)
        self.assertEqual(counts["2026-10-09"], 1)

    def test_timeline_is_scoped_and_supports_all_periods(self):
        for period in (7, 30, 90, 365):
            data = self.run_widget(self.cabo2, "timeline", period=period)
            self.assertEqual(len(data["points"]), period)
        self.assertEqual(self.run_widget(self.cabo2, "timeline", period=7)["total"], 1)

    def test_gender_distribution(self):
        data = self.run_widget(self.admin, "by_gender")
        rows = {r["key"]: r["count"] for r in data["rows"]}
        self.assertEqual(rows, {"M": 2, "F": 3, "O": 0, "N": 0, "unknown": 1})
        self.assertEqual(data["total"], 6)

    def test_support_distribution_uses_unclassified_label(self):
        data = self.run_widget(self.admin, "by_support")
        rows = {r["key"]: r for r in data["rows"]}
        self.assertEqual(rows["APOIADOR"]["count"], 1)
        self.assertEqual(rows["unknown"]["label"], "Sem classificação")
        self.assertEqual(rows["unknown"]["count"], 3)

    def test_source_distribution(self):
        data = self.run_widget(self.admin, "by_source")
        rows = {r["key"]: r["count"] for r in data["rows"]}
        self.assertEqual((rows["LINK"], rows["QRCODE"], rows["MANUAL"]), (4, 1, 1))  # v5/v6 usam a origem padrão (link)

    def test_age_buckets(self):
        data = self.run_widget(self.admin, "by_age")
        rows = {r["key"]: r["count"] for r in data["rows"]}
        # nascidos em 2000 (26), 1960 (66), 1985 (41); os outros 3 sem data
        self.assertEqual(rows, {"16-24": 0, "25-34": 1, "35-44": 1, "45-59": 0, "60+": 1, "unknown": 3})
        self.assertEqual(data["total"], 6)
        self.assertEqual(self.run_widget(self.cabo2, "by_age")["total"], 2)

    def test_age_bucket_boundary_is_exact(self):
        make_voter(self.a, self.cabo1, 40, birth_date=dt.date(2001, 10, 10))  # faz 25 hoje
        make_voter(self.a, self.cabo1, 41, birth_date=dt.date(2001, 10, 11))  # ainda tem 24
        rows = {r["key"]: r["count"] for r in self.run_widget(self.cabo1, "by_age")["rows"]}
        self.assertEqual(rows["25-34"], 2)  # v1 (26 anos) e quem faz 25 hoje
        self.assertEqual(rows["16-24"], 1)  # quem ainda tem 24 anos

    def test_widget_filters_apply_inside_scope(self):
        data = self.run_widget(self.admin, "kpi_total", filters={"genders": ["F"]})
        self.assertEqual(data["total"], 3)
        data = self.run_widget(self.admin, "kpi_total", filters={"cities": ["Valinhos"], "genders": ["M"]})
        self.assertEqual(data["total"], 1)
        data = self.run_widget(self.cabo1, "kpi_total", filters={"cities": ["Valinhos"]})
        self.assertEqual(data["total"], 0)


class GoalsAndNoteTests(DataBase):
    def test_goals_progress(self):
        data = self.run_widget(self.admin, "goals_progress", limit=10)
        by_name = {r["name"]: r for r in data["rows"]}
        self.assertEqual(set(by_name), {"Carlos Coord", "Ana Cabo", "Bia Cabo"})
        self.assertEqual(by_name["Bia Cabo"]["pct"], 10.0)
        self.assertEqual(by_name["Ana Cabo"]["pct"], 6.0)
        self.assertEqual(by_name["Carlos Coord"]["pct"], 1.0)
        self.assertEqual([r["name"] for r in data["rows"]], ["Bia Cabo", "Ana Cabo", "Carlos Coord"])
        self.assertEqual(data["without_goal"], 2)  # Dora e Zeca
        self.assertEqual(len(self.run_widget(self.admin, "goals_progress", limit=3)["rows"]), 3)

    def test_goals_progress_is_scoped(self):
        data = self.run_widget(self.cabo1, "goals_progress", limit=10)
        self.assertEqual([r["name"] for r in data["rows"]], ["Ana Cabo"])
        self.assertNotIn("Cabo da Beta", [r["name"] for r in self.run_widget(self.admin, "goals_progress", limit=50)["rows"]])

    def test_note_has_no_server_data(self):
        self.assertEqual(self.run_widget(self.cabo1, "note", text="Reunião às 19h"), {"type": "note"})


class BroadcastWidgetTests(DataBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.bc_admin = Broadcast.objects.create(campaign=cls.a, name="Disparo do admin", created_by=cls.admin, status="COMPLETED",
                                               total_recipients=10, sent_count=10, delivered_count=8, read_count=4, failed_count=2)  # fmt: skip
        cls.bc_coord = Broadcast.objects.create(campaign=cls.a, name="Disparo do coordenador", created_by=cls.coord1, status="RUNNING",
                                               total_recipients=5, sent_count=2)  # fmt: skip
        cls.bc_other = Broadcast.objects.create(campaign=cls.b, name="Segredo da Beta", created_by=cls.admin_b, status="COMPLETED")
        statuses = {cls.bc_admin: ["READ", "READ", "DELIVERED", "SENT", "FAILED"], cls.bc_coord: ["SENT", "PENDING"], cls.bc_other: ["READ"]}
        n = 0
        for bc, items in statuses.items():
            for status in items:
                n += 1
                BroadcastMessage.objects.create(broadcast=bc, campaign=bc.campaign, phone=f"551180000{n:04d}", rendered_body="oi", status=status)
        BroadcastMessage.objects.update(created_at=days_ago(1))  # dentro do período, relativo ao NOW fixo dos testes

    def test_admin_sees_all_campaign_broadcasts(self):
        data = self.run_widget(self.admin, "broadcasts", period=30)
        self.assertFalse(data["locked"])
        self.assertEqual(data["scope"], "campaign")
        self.assertEqual((data["read"], data["delivered"], data["sent"], data["failed"], data["pending"]), (2, 3, 5, 1, 1))
        self.assertEqual({b["name"] for b in data["recent"]}, {"Disparo do admin", "Disparo do coordenador"})
        self.assertNotIn("Segredo da Beta", json.dumps(data))

    def test_non_admin_only_sees_broadcasts_he_created(self):
        data = self.run_widget(self.coord1, "broadcasts", period=30)
        self.assertEqual(data["scope"], "own")
        self.assertEqual([b["name"] for b in data["recent"]], ["Disparo do coordenador"])
        self.assertEqual((data["sent"], data["read"]), (1, 0))

    def test_locked_without_disparos_view(self):
        data = self.run_widget(self.cabo1, "broadcasts", period=30)  # CABO não tem disparos.view por padrão
        self.assertTrue(data["locked"])
        self.assertEqual(data["recent"], [])
        RolePermission.objects.filter(campaign=self.a, role=Role.COORDENADOR, module="disparos").update(can_view=False)
        self.assertTrue(self.run_widget(self.coord1, "broadcasts", period=30)["locked"])

    def test_rates(self):
        data = self.run_widget(self.admin, "broadcasts", period=30)
        self.assertEqual(data["delivery_rate"], 60.0)  # 3 entregues / 5 enviadas
        self.assertEqual(data["read_rate"], 66.7)  # 2 lidas / 3 entregues


class DashboardDataTests(DataBase):
    def test_every_widget_type_is_json_serializable_for_every_role(self):
        for user in (self.admin, self.coord1, self.cabo1, self.cabo_idle):
            widgets = [create_widget(t, id_=f"w-{t}") for t in WIDGET_CATALOG]
            result = compute_dashboard_data(user, widgets, now=NOW)
            self.assertEqual(set(result), {w["id"] for w in widgets})
            for wid, payload in result.items():
                self.assertNotIn("error", payload, f"{user.role} {wid}")
            json.dumps(result)  # não levanta exceção

    def test_all_presets_compute_for_a_brand_new_campaign_without_voters(self):
        empty = make_campaign("vazia")
        owner = make_user(empty, "admin@vazia.com", Role.ADMIN)
        for key in ("visao_geral", "equipe", "territorial", "comunicacao"):
            result = compute_dashboard_data(owner, preset_widgets(key), now=NOW)
            self.assertFalse([k for k, v in result.items() if "error" in v], key)

    def test_failing_widget_does_not_break_the_others(self):
        boom = mock.Mock(side_effect=RuntimeError("falhou com dado pessoal 11999999999"))
        with mock.patch.dict(dash_data._COMPUTE, {"kpi_total": boom}):
            with self.assertLogs(dash_data.logger, level="WARNING") as logs:
                result = compute_dashboard_data(self.admin, [widget("kpi_total", "a"), widget("kpi_today", "b")], now=NOW)
        self.assertEqual(result["a"], {"error": dash_data.ERROR_MESSAGE})
        self.assertIn("today", result["b"])
        self.assertNotIn("11999999999", "".join(logs.output))  # o log só registra tipo e classe do erro

    def test_identical_widgets_are_computed_once(self):
        real = dash_data._COMPUTE["timeline"]
        spy = mock.Mock(side_effect=real)
        with mock.patch.dict(dash_data._COMPUTE, {"timeline": spy}):
            result = compute_dashboard_data(
                self.admin,
                [widget("timeline", "a", period=30), widget("timeline", "b", period=30, title="Outro título"), widget("timeline", "c", period=7)],
                now=NOW,
            )
        self.assertEqual(spy.call_count, 2)
        self.assertEqual(result["a"], result["b"])
        self.assertNotEqual(result["a"], result["c"])

    def test_query_count_is_bounded_and_independent_of_voters(self):
        widgets = preset_widgets("visao_geral") + preset_widgets("equipe")
        with CaptureQueriesContext(connection) as small:
            compute_dashboard_data(self.admin, widgets, now=NOW)
        for n in range(100, 140):
            make_voter(self.a, self.cabo1 if n % 2 else self.cabo2, n, days_ago(n % 10), neighborhood=f"Bairro {n % 7}")
        with CaptureQueriesContext(connection) as large:
            compute_dashboard_data(self.admin, widgets, now=NOW)
        self.assertEqual(len(small), len(large))  # sem N+1: mais eleitores não geram mais consultas
        self.assertLess(len(large), 45)

    def test_data_context_caches_team_and_permissions(self):
        ctx = DataContext(self.cabo1, now=NOW)
        first_team, first_perms = ctx.team(), ctx.perms
        with self.assertNumQueries(0):
            self.assertIs(ctx.team(), first_team)
            self.assertIs(ctx.perms, first_perms)
