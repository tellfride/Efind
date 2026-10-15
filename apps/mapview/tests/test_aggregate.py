"""Agregação dos dados do mapa: linhas de apoiadores → totais, bairros, pontos e limites (lógica pura)."""

import json

from django.test import SimpleTestCase

from apps.core.constants import GeoStatus, SupportLevel
from apps.mapview.aggregate import (
    MAP_POINT_LIMIT,
    UNKNOWN_MEMBER,
    UNKNOWN_NEIGHBORHOOD,
    aggregate_map_data,
    build_map_payload,
    clean_text,
    neighborhood_key,
    sample_points,
    valid_coordinates,
)

ANA, BETO, CARLA = "u-ana", "u-beto", "u-carla"
NAMES = {ANA: "Ana", BETO: "Beto", CARLA: "Carla"}


def row(n, lat=None, lng=None, *, bairro="Centro", city="Campinas", status=GeoStatus.OK, support="", messageable=False, by=ANA):
    return {
        "id": f"id-{n}",
        "latitude": lat,
        "longitude": lng,
        "geo_status": status if lat is not None else GeoStatus.PENDING,
        "neighborhood": bairro,
        "city": city,
        "support_level": support,
        "messageable": messageable,
        "registered_by_id": by,
    }


def run(rows, **kwargs):
    kwargs.setdefault("member_names", NAMES)
    kwargs.setdefault("can_view_voters", True)
    return aggregate_map_data(rows, **kwargs)


class HelperTests(SimpleTestCase):
    def test_valid_coordinates(self):
        self.assertTrue(valid_coordinates(-22.9, -47.06))
        self.assertTrue(valid_coordinates("-22.9", "-47.06"))
        for bad in (
            (None, -47.0),
            (-22.9, None),
            (0, 0),
            (91, 10),
            (10, 181),
            (float("nan"), 1),
            (float("inf"), 1),
            ("abc", 1),
            (True, False),
        ):
            self.assertFalse(valid_coordinates(*bad), bad)

    def test_equator_or_meridian_alone_are_valid(self):
        self.assertTrue(valid_coordinates(0, -47.0))
        self.assertTrue(valid_coordinates(-22.0, 0))

    def test_clean_text(self):
        self.assertEqual(clean_text("  Jardim   das  Flores "), "Jardim das Flores")
        self.assertEqual(clean_text(None), "")

    def test_neighborhood_key_separates_name_and_city(self):
        self.assertNotEqual(neighborhood_key("Centro", "Campinas"), neighborhood_key("Centro", "Valinhos"))
        self.assertNotEqual(neighborhood_key("A", "BC"), neighborhood_key("AB", "C"))

    def test_sample_points(self):
        items = list(range(100))
        self.assertEqual(sample_points(items, 200), items)
        sampled = sample_points(items, 10)
        self.assertEqual(len(sampled), 10)
        self.assertEqual(sampled, sorted(sampled))
        self.assertEqual(sampled[0], 0)
        self.assertEqual(sample_points(items, 10), sampled)  # determinística
        self.assertEqual(sample_points(items, 0), [])


class TotalsTests(SimpleTestCase):
    def test_empty(self):
        data = run([])
        self.assertEqual(data["totals"], {"voters": 0, "with_geo": 0, "without_geo": 0, "approximate": 0})
        self.assertEqual(data["neighborhoods"], [])
        self.assertEqual(data["neighborhoods_without_geo"], [])
        self.assertEqual(data["points"], [])
        self.assertIsNone(data["bounds"])
        self.assertFalse(data["truncated"])

    def test_totals(self):
        rows = [
            row(1, -22.90, -47.06),
            row(2, -22.92, -47.08, status=GeoStatus.APPROXIMATE),
            row(3),  # sem coordenadas
            row(4, 0, 0),  # coordenadas inutilizáveis contam como sem localização
        ]
        data = run(rows)
        self.assertEqual(data["totals"], {"voters": 4, "with_geo": 2, "without_geo": 2, "approximate": 1})

    def test_approximate_only_counts_geocoded_voters(self):
        data = run([row(1, status=GeoStatus.APPROXIMATE), row(2, -22.9, -47.0, status=GeoStatus.APPROXIMATE)])
        self.assertEqual(data["totals"]["approximate"], 1)

    def test_can_view_voters_flag_is_passed_through(self):
        self.assertTrue(run([], can_view_voters=True)["can_view_voters"])
        self.assertFalse(run([], can_view_voters=False)["can_view_voters"])


class NeighborhoodTests(SimpleTestCase):
    def test_centroid_is_mean_of_geocoded_voters_only(self):
        rows = [row(1, -22.0, -47.0), row(2, -24.0, -49.0), row(3)]  # o 3º não entra na média
        (n,) = run(rows)["neighborhoods"]
        self.assertEqual((n["lat"], n["lng"]), (-23.0, -48.0))
        self.assertEqual(n["count"], 3)
        self.assertEqual(n["mapped"], 2)

    def test_same_name_in_different_cities_is_separate(self):
        rows = [row(1, -22.0, -47.0, city="Campinas"), row(2, -23.0, -46.0, city="Valinhos")]
        data = run(rows)
        self.assertEqual(sorted(n["city"] for n in data["neighborhoods"]), ["Campinas", "Valinhos"])
        self.assertEqual(len({n["key"] for n in data["neighborhoods"]}), 2)

    def test_whitespace_variants_are_merged(self):
        rows = [row(1, -22.0, -47.0, bairro="Jardim  Flores"), row(2, -22.0, -47.0, bairro=" Jardim Flores ")]
        (n,) = run(rows)["neighborhoods"]
        self.assertEqual((n["name"], n["count"]), ("Jardim Flores", 2))

    def test_messageable_and_supporters(self):
        rows = [
            row(1, -22.0, -47.0, messageable=True, support=SupportLevel.APOIADOR),
            row(2, -22.0, -47.0, messageable=True, support=SupportLevel.INDECISO),
            row(3, -22.0, -47.0, messageable=False, support=SupportLevel.APOIADOR),
            row(4, -22.0, -47.0),
        ]
        (n,) = run(rows)["neighborhoods"]
        self.assertEqual((n["count"], n["messageable"], n["supporters"]), (4, 2, 2))

    def test_top_members_are_top_three_by_count(self):
        rows = (
            [row(i, -22.0, -47.0, by=ANA) for i in range(1, 5)]  # 4
            + [row(i, -22.0, -47.0, by=BETO) for i in range(5, 8)]  # 3
            + [row(i, -22.0, -47.0, by=CARLA) for i in range(8, 10)]  # 2
            + [row(10, -22.0, -47.0, by="u-sem-nome")]  # 1
        )
        (n,) = run(rows)["neighborhoods"]
        self.assertEqual(n["top_members"], [{"name": "Ana", "count": 4}, {"name": "Beto", "count": 3}, {"name": "Carla", "count": 2}])

    def test_top_members_unknown_user_gets_generic_name(self):
        (n,) = run([row(1, -22.0, -47.0, by="outro")])["neighborhoods"]
        self.assertEqual(n["top_members"], [{"name": UNKNOWN_MEMBER, "count": 1}])

    def test_top_members_respects_custom_limit(self):
        rows = [row(1, -22.0, -47.0, by=ANA), row(2, -22.0, -47.0, by=BETO)]
        (n,) = run(rows, top_members=1)["neighborhoods"]
        self.assertEqual(len(n["top_members"]), 1)

    def test_sorted_by_count_then_name(self):
        rows = (
            [row(1, -22.0, -47.0, bairro="Zeta")]
            + [row(i, -22.0, -47.0, bairro="Alfa") for i in range(2, 4)]
            + [row(i, -22.0, -47.0, bairro="Centro") for i in range(4, 6)]
            + [row(6, -22.0, -47.0, bairro="Ábaco")]
        )
        names = [n["name"] for n in run(rows)["neighborhoods"]]
        self.assertEqual(names, ["Alfa", "Centro", "Ábaco", "Zeta"])

    def test_blank_neighborhood_is_labeled(self):
        (n,) = run([row(1, -22.0, -47.0, bairro="")])["neighborhoods"]
        self.assertEqual(n["name"], UNKNOWN_NEIGHBORHOOD)
        self.assertFalse(n["known"])

    def test_neighborhood_without_any_geo_goes_to_separate_list(self):
        rows = [row(1, -22.0, -47.0, bairro="Centro"), row(2, bairro="Longe"), row(3, bairro="Longe"), row(4, bairro="Aqui")]
        data = run(rows)
        self.assertEqual([n["name"] for n in data["neighborhoods"]], ["Centro"])
        self.assertEqual(
            [(n["name"], n["count"]) for n in data["neighborhoods_without_geo"]], [("Longe", 2), ("Aqui", 1)]
        )
        for item in data["neighborhoods_without_geo"]:
            self.assertEqual({"name", "city", "count", "key", "known"} - set(item), set())

    def test_totals_match_sum_of_groups(self):
        rows = [row(i, -22.0 - i / 100, -47.0, bairro=f"B{i % 3}") for i in range(1, 11)] + [row(11, bairro="B9")]
        data = run(rows)
        listed = sum(n["count"] for n in data["neighborhoods"]) + sum(n["count"] for n in data["neighborhoods_without_geo"])
        self.assertEqual(listed, data["totals"]["voters"])


class PointsAndBoundsTests(SimpleTestCase):
    def test_points_have_only_id_and_coordinates(self):
        data = run([row(1, -22.123456789, -47.987654321)])
        (p,) = data["points"]
        self.assertEqual(set(p), {"id", "lat", "lng"})
        self.assertEqual(p["id"], "id-1")
        self.assertAlmostEqual(p["lat"], -22.12346, places=5)

    def test_points_only_include_geocoded(self):
        data = run([row(1, -22.0, -47.0), row(2), row(3, 0, 0)])
        self.assertEqual([p["id"] for p in data["points"]], ["id-1"])

    def test_bounds(self):
        data = run([row(1, -22.0, -47.5), row(2, -23.5, -46.0), row(3, -21.0, -48.0)])
        self.assertEqual(data["bounds"], [[-23.5, -48.0], [-21.0, -46.0]])

    def test_single_point_bounds_are_degenerate_but_present(self):
        data = run([row(1, -22.0, -47.0)])
        self.assertEqual(data["bounds"], [[-22.0, -47.0], [-22.0, -47.0]])

    def test_point_limit_truncates_and_flags(self):
        rows = [row(i, -22.0 - i / 10_000, -47.0) for i in range(1, 51)]
        data = run(rows, point_limit=10)
        self.assertEqual(len(data["points"]), 10)
        self.assertTrue(data["truncated"])
        self.assertEqual(data["totals"]["with_geo"], 50)  # totais não são afetados pela amostra
        self.assertEqual(sum(n["count"] for n in data["neighborhoods"]), 50)

    def test_no_truncation_at_exact_limit(self):
        rows = [row(i, -22.0, -47.0) for i in range(1, 11)]
        data = run(rows, point_limit=10)
        self.assertEqual(len(data["points"]), 10)
        self.assertFalse(data["truncated"])

    def test_default_limit_is_twenty_thousand(self):
        self.assertEqual(MAP_POINT_LIMIT, 20_000)


class PrivacyTests(SimpleTestCase):
    def test_personal_data_in_rows_never_reaches_the_payload(self):
        dirty = row(1, -22.0, -47.0)
        dirty.update({"name": "Maria Secreta", "phone": "5511999998888", "email": "maria@secreta.com"})
        payload = build_map_payload([dirty], member_names=NAMES, can_view_voters=True)
        blob = json.dumps(payload)
        for secret in ("Maria Secreta", "5511999998888", "maria@secreta.com"):
            self.assertNotIn(secret, blob)

    def test_payload_is_json_serializable(self):
        payload = build_map_payload([row(1, -22.0, -47.0), row(2)], member_names=NAMES, can_view_voters=False)
        self.assertEqual(json.loads(json.dumps(payload))["totals"]["voters"], 2)


class PayloadScaleTests(SimpleTestCase):
    def test_payload_decorates_neighborhoods_with_color_radius_and_legend(self):
        rows = [row(i, -22.0, -47.0, bairro="Grande") for i in range(1, 21)] + [row(30, -23.0, -46.0, bairro="Pequeno")]
        payload = build_map_payload(rows, member_names=NAMES, can_view_voters=True)
        big, small = payload["neighborhoods"]
        self.assertEqual((big["name"], small["name"]), ("Grande", "Pequeno"))
        self.assertGreater(big["radius"], small["radius"])
        self.assertNotEqual(big["color"], small["color"])
        self.assertEqual(payload["legend"]["max_count"], 20)
        self.assertEqual(payload["legend"]["bins"][-1]["max"], 20)
        self.assertEqual(payload["legend"]["bins"][-1]["color"], big["color"])

    def test_empty_payload_has_empty_legend(self):
        payload = build_map_payload([], member_names={}, can_view_voters=False)
        self.assertEqual(payload["legend"], {"max_count": 0, "bins": []})
