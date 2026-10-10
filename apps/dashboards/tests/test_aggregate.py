"""Funções puras de agregação: linha do tempo, faixas etárias, rankings, comparação de períodos (sem banco)."""

import datetime as dt

from django.test import SimpleTestCase

from apps.core.access import SAO_PAULO
from apps.core.constants import Role
from apps.dashboards import aggregate as agg

UTC = dt.timezone.utc


def member(id_, name, role=Role.CABO, active=True, goal=None, parent=None, parent_name=None, parent_role=None):
    return agg.TeamMember(
        id=id_, name=name, role=role, active=active, goal=goal, parent_id=parent, parent_name=parent_name, parent_role=parent_role
    )


class PeriodTests(SimpleTestCase):
    def test_today_uses_sao_paulo_not_utc(self):
        # 01:30 UTC de 11/10 ainda é 22:30 de 10/10 em São Paulo
        now = dt.datetime(2026, 10, 11, 1, 30, tzinfo=UTC)
        self.assertEqual(agg.sao_paulo_today(now), dt.date(2026, 10, 10))
        self.assertEqual(agg.day_key(now), "2026-10-10")

    def test_period_range_includes_today_and_previous_period_has_same_length(self):
        now = dt.datetime(2026, 10, 10, 15, 0, tzinfo=UTC)
        rng = agg.period_range(30, now)
        self.assertEqual(rng.start_day, dt.date(2026, 9, 11))
        self.assertEqual(rng.end_day, dt.date(2026, 10, 10))
        self.assertEqual(rng.start, dt.datetime(2026, 9, 11, tzinfo=SAO_PAULO))
        self.assertEqual((rng.start - rng.previous_start).days, 30)

    def test_today_range(self):
        now = dt.datetime(2026, 10, 10, 15, 0, tzinfo=UTC)
        today, yesterday = agg.today_range(now)
        self.assertEqual(today, dt.datetime(2026, 10, 10, tzinfo=SAO_PAULO))
        self.assertEqual(yesterday, dt.datetime(2026, 10, 9, tzinfo=SAO_PAULO))

    def test_compare_periods(self):
        self.assertEqual(agg.compare_periods(15, 10), {"current": 15, "previous": 10, "delta_pct": 50.0, "trend": "up"})
        self.assertEqual(agg.compare_periods(5, 10)["delta_pct"], -50.0)
        self.assertEqual(agg.compare_periods(5, 10)["trend"], "down")
        flat = agg.compare_periods(7, 7)
        self.assertEqual((flat["delta_pct"], flat["trend"]), (0.0, "flat"))

    def test_compare_periods_without_previous_has_no_percentage(self):
        result = agg.compare_periods(4, 0)
        self.assertIsNone(result["delta_pct"])
        self.assertEqual(result["trend"], "up")
        self.assertEqual(agg.compare_periods(0, 0)["trend"], "flat")

    def test_percent(self):
        self.assertEqual(agg.percent(1, 3), 33.3)
        self.assertEqual(agg.percent(150, 100), 150.0)
        self.assertIsNone(agg.percent(5, 0))
        self.assertIsNone(agg.percent(5, None))


class TimelineTests(SimpleTestCase):
    def test_missing_days_are_filled_with_zero(self):
        points = agg.fill_timeline({"2026-10-02": 3, "2026-10-04": 1}, "2026-10-01", "2026-10-05")
        self.assertEqual([p["date"] for p in points], ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05"])
        self.assertEqual([p["count"] for p in points], [0, 3, 0, 1, 0])

    def test_single_day_and_order(self):
        self.assertEqual(agg.fill_timeline({}, "2026-10-01", "2026-10-01"), [{"date": "2026-10-01", "count": 0}])
        self.assertEqual(agg.fill_timeline({}, "2026-10-02", "2026-10-01"), [])

    def test_build_timeline_groups_instants_by_sao_paulo_day(self):
        instants = [
            dt.datetime(2026, 10, 10, 2, 30, tzinfo=UTC),  # 23:30 de 09/10 em SP
            dt.datetime(2026, 10, 10, 3, 0, tzinfo=UTC),  # 00:00 de 10/10 em SP
            dt.datetime(2026, 10, 10, 18, 0, tzinfo=UTC),
        ]
        points = agg.build_timeline(instants, "2026-10-08", "2026-10-10")
        self.assertEqual({p["date"]: p["count"] for p in points}, {"2026-10-08": 0, "2026-10-09": 1, "2026-10-10": 2})

    def test_period_of_365_days_has_365_points(self):
        rng = agg.period_range(365, dt.datetime(2026, 10, 10, 12, tzinfo=UTC))
        self.assertEqual(len(agg.fill_timeline({}, rng.start_key, rng.end_key)), 365)


class AgeTests(SimpleTestCase):
    today = dt.date(2026, 10, 10)

    def test_age_at_and_bucket_keys(self):
        self.assertEqual(agg.age_at(dt.date(2000, 10, 10), self.today), 26)
        self.assertEqual(agg.age_at(dt.date(2000, 10, 11), self.today), 25)
        cases = {15: "unknown", 16: "16-24", 24: "16-24", 25: "25-34", 34: "25-34", 35: "35-44", 44: "35-44", 45: "45-59", 59: "45-59", 60: "60+", 99: "60+"}
        for age, key in cases.items():
            self.assertEqual(agg.age_bucket_key(age), key, age)
        self.assertEqual(agg.age_bucket_key(None), "unknown")

    def test_bucket_ages_counts_every_bucket_and_unknown(self):
        births = [
            dt.date(2005, 1, 1),  # 21
            dt.date(2001, 10, 10),  # 25
            dt.date(1990, 5, 5),  # 36
            dt.date(1975, 3, 3),  # 51
            dt.date(1950, 1, 1),  # 76
            dt.date(2020, 1, 1),  # 6 → não informado
            None,
        ]
        rows = agg.bucket_ages(births, self.today)
        self.assertEqual([r["label"] for r in rows], ["16–24", "25–34", "35–44", "45–59", "60+", "Não informado"])
        self.assertEqual([r["count"] for r in rows], [1, 1, 1, 1, 1, 2])

    def test_birth_date_bounds_match_age_arithmetic(self):
        lte, gt = agg.birth_date_bounds(25, 34, self.today)
        self.assertEqual(lte, dt.date(2001, 10, 10))  # fez 25 hoje
        self.assertEqual(gt, dt.date(1991, 10, 10))  # nascido nesse dia já tem 35
        self.assertEqual(agg.birth_date_bounds(60, None, self.today)[1], None)

    def test_leap_day_birthday(self):
        self.assertEqual(agg.minus_years(dt.date(2028, 2, 29), 1), dt.date(2027, 2, 28))


class DistributionTests(SimpleTestCase):
    def test_to_distribution_keeps_order_and_unknown(self):
        out = agg.to_distribution([("F", 3), ("M", 5), ("", 2), (None, 1)], ["M", "F", "O"], {"M": "Masculino", "F": "Feminino", "O": "Outro"})
        self.assertEqual([r["key"] for r in out["rows"]], ["M", "F", "O", "unknown"])
        self.assertEqual([r["count"] for r in out["rows"]], [5, 3, 0, 3])
        self.assertEqual(out["total"], 11)
        self.assertEqual(out["rows"][-1]["label"], "Não informado")

    def test_to_distribution_omits_unknown_when_zero(self):
        out = agg.to_distribution([("M", 2)], ["M", "F"], {"M": "M", "F": "F"})
        self.assertEqual([r["key"] for r in out["rows"]], ["M", "F"])

    def test_top_n_merges_spellings_and_reports_rest(self):
        rows = [("Centro", 5), ("centro", 2), ("Cambuí", 4), ("Barão Geraldo", 3), ("Taquaral", 1), ("", 7), (None, 1)]
        out = agg.top_n(rows, 2)
        self.assertEqual([(r["label"], r["count"]) for r in out["rows"]], [("Centro", 7), ("Cambuí", 4)])
        self.assertEqual(out["others"], 4)
        self.assertEqual(out["others_categories"], 2)
        self.assertEqual(out["missing"], 8)
        self.assertEqual(out["total"], 23)

    def test_top_n_with_zero_limit_and_empty_input(self):
        self.assertEqual(agg.top_n([], 5)["rows"], [])
        self.assertEqual(agg.top_n([("A", 1)], 0)["rows"], [])


class RankingTests(SimpleTestCase):
    def setUp(self):
        self.coord = member("c1", "Carlos Coord", Role.COORDENADOR, goal=100, parent="adm", parent_name="Admin", parent_role=Role.ADMIN)
        self.team = [
            member("adm", "Admin", Role.ADMIN),
            self.coord,
            member("a", "Ana Cabo", goal=50, parent="c1", parent_name="Carlos Coord", parent_role=Role.COORDENADOR),
            member("b", "Bruno Cabo", parent="c1", parent_name="Carlos Coord", parent_role=Role.COORDENADOR),
            member("z", "Zeca Cabo", active=False, parent="c1", parent_name="Carlos Coord", parent_role=Role.COORDENADOR),
            member("d", "Duda Direta", parent="adm", parent_name="Admin", parent_role=Role.ADMIN),
        ]
        last = dt.datetime(2026, 10, 9, 12, tzinfo=UTC)
        self.stats = agg.RegistrantStats(
            total={"a": 40, "b": 12, "c1": 3, "d": 5},
            in_period={"a": 8, "b": 8, "c1": 1, "d": 0},
            last_at={"a": last, "b": None, "c1": last, "d": last},
        )

    def test_member_ranking_order_and_fields(self):
        rows = agg.compute_member_ranking(self.team, self.stats)
        # ordem: no período ↓, total ↓, nome; admin sem cadastros e inativo sem cadastros ficam de fora
        self.assertEqual([r["id"] for r in rows], ["a", "b", "c1", "d"])
        first = rows[0]
        self.assertEqual((first["total"], first["in_period"], first["goal"], first["goal_pct"]), (40, 8, 50, 80.0))
        self.assertEqual(first["coordinator_name"], "Carlos Coord")
        self.assertEqual(first["last_at"], "2026-10-09T12:00:00+00:00")
        self.assertIsNone(rows[1]["goal"])
        self.assertIsNone(rows[1]["goal_pct"])
        self.assertIsNone(rows[1]["last_at"])
        self.assertIsNone(rows[3]["coordinator_name"])  # cabo ligado direto ao admin

    def test_member_ranking_includes_active_members_without_registrations(self):
        stats = agg.RegistrantStats(total={}, in_period={}, last_at={})
        rows = agg.compute_member_ranking(self.team, stats)
        self.assertEqual({r["id"] for r in rows}, {"c1", "a", "b", "d"})
        self.assertTrue(all(r["total"] == 0 for r in rows))

    def test_member_ranking_keeps_inactive_member_with_registrations(self):
        stats = agg.RegistrantStats(total={"z": 4}, in_period={"z": 0}, last_at={})
        rows = agg.compute_member_ranking(self.team, stats)
        zeca = next(r for r in rows if r["id"] == "z")
        self.assertFalse(zeca["active"])

    def test_filter_members_by_voter_filters(self):
        by_cabo = agg.filter_members_by_voter_filters(self.team, {"registered_by_ids": ["a", "b"]})
        self.assertEqual([m.id for m in by_cabo], ["a", "b"])
        by_coord = agg.filter_members_by_voter_filters(self.team, {"coordinator_ids": ["c1"]})
        self.assertEqual({m.id for m in by_coord}, {"c1", "a", "b", "z"})
        self.assertEqual(len(agg.filter_members_by_voter_filters(self.team, None)), len(self.team))

    def test_coordinator_ranking_aggregates_the_network(self):
        result = agg.compute_coordinator_ranking(self.team, self.stats)
        self.assertEqual(len(result["rows"]), 1)
        row = result["rows"][0]
        self.assertEqual((row["total"], row["in_period"], row["own"]), (55, 17, 3))
        self.assertEqual(row["cabos"], 2)  # o cabo inativo não conta
        self.assertEqual((row["goal"], row["goal_pct"]), (100, 55.0))
        self.assertEqual(result["others"], {"total": 5, "in_period": 0})  # cabo ligado direto ao admin

    def test_coordinator_goal_falls_back_to_sum_of_cabo_goals(self):
        coord = member("c2", "Sem Meta", Role.COORDENADOR)
        cabo = member("k", "K", goal=30, parent="c2", parent_name="Sem Meta", parent_role=Role.COORDENADOR)
        stats = agg.RegistrantStats(total={"k": 15}, in_period={"k": 15}, last_at={})
        row = agg.compute_coordinator_ranking([coord, cabo], stats)["rows"][0]
        self.assertEqual((row["goal"], row["goal_pct"]), (30, 50.0))

    def test_goals_progress_sorted_by_percentage(self):
        result = agg.compute_goals_progress(self.team, {"a": 40, "c1": 150})
        self.assertEqual([r["id"] for r in result["rows"]], ["c1", "a"])
        self.assertEqual([r["pct"] for r in result["rows"]], [150.0, 80.0])
        self.assertEqual(result["without_goal"], 2)  # Bruno e Duda (Zeca está inativo; o admin não conta)

    def test_team_goal_sum_counts_only_active_members_with_goal(self):
        self.assertEqual(agg.team_goal_sum(self.team), (150, 2))
        self.assertEqual(agg.team_goal_sum([]), (0, 0))

    def test_broadcast_rates(self):
        rates = agg.broadcast_rates({"SENT": 10, "DELIVERED": 30, "READ": 20, "FAILED": 5, "PENDING": 3, "SENDING": 2})
        self.assertEqual((rates["sent"], rates["delivered"], rates["read"], rates["failed"], rates["pending"]), (60, 50, 20, 5, 5))
        self.assertEqual(rates["delivery_rate"], 83.3)
        self.assertEqual(rates["read_rate"], 40.0)
        empty = agg.broadcast_rates({})
        self.assertIsNone(empty["delivery_rate"])
        self.assertIsNone(empty["read_rate"])
