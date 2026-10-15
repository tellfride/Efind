"""Catálogo de widgets e validação do JSON salvo (lógica pura, sem banco)."""

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from apps.core.permissions import full_permissions, no_permissions
from apps.dashboards import widgets as w
from apps.dashboards.presets import DASHBOARD_PRESET_KEYS, DASHBOARD_PRESETS, preset_widgets

EXPECTED_TYPES = {
    "kpi_total", "kpi_today", "kpi_period", "kpi_goal", "kpi_messageable", "kpi_team",
    "ranking_members", "ranking_coordinators", "timeline",
    "by_neighborhood", "by_city", "by_gender", "by_support", "by_source", "by_age",
    "recent_voters", "broadcasts", "goals_progress", "note",
}  # fmt: skip


def widget(id_="w1", type_="kpi_total", size="sm", **config):
    return {"id": id_, "type": type_, "size": size, "config": config}


class CatalogTests(SimpleTestCase):
    def test_catalog_has_every_required_type(self):
        self.assertEqual(set(w.WIDGET_CATALOG), EXPECTED_TYPES)

    def test_every_definition_is_complete_and_grouped(self):
        for definition in w.WIDGET_CATALOG.values():
            self.assertTrue(definition.label and definition.description)
            self.assertIn(definition.group, w.WIDGET_GROUP_KEYS)
            self.assertIn(definition.default_size, w.WIDGET_SIZES)

    def test_catalog_for_client_marks_availability_by_permission(self):
        by_type = {c["type"]: c for c in w.catalog_for_client(no_permissions())}
        self.assertFalse(by_type["broadcasts"]["available"])
        self.assertFalse(by_type["recent_voters"]["available"])
        self.assertTrue(by_type["kpi_total"]["available"])
        by_type = {c["type"]: c for c in w.catalog_for_client(full_permissions())}
        self.assertTrue(by_type["broadcasts"]["available"])

    def test_catalog_by_group_covers_all_groups(self):
        groups = {g["key"]: g["items"] for g in w.catalog_by_group()}
        self.assertEqual(set(groups), set(w.WIDGET_GROUP_KEYS))
        self.assertEqual(sum(len(items) for items in groups.values()), len(EXPECTED_TYPES))

    def test_create_widget_uses_catalog_defaults(self):
        created = w.create_widget("ranking_members")
        self.assertEqual(created["size"], "full")
        self.assertEqual(created["config"], {"period": 30, "limit": 10})
        self.assertEqual(w.create_widget("note")["config"], {"text": ""})
        self.assertNotEqual(w.create_widget("kpi_total")["id"], w.create_widget("kpi_total")["id"])


class ValidateWidgetsTests(SimpleTestCase):
    def test_accepts_valid_list(self):
        out = w.validate_widgets([widget("a", "ranking_members", "full", period=7, limit=20), widget("b", "kpi_total")])
        self.assertEqual([x["id"] for x in out], ["a", "b"])
        self.assertEqual(out[0]["config"], {"period": 7, "limit": 20})

    def test_rejects_non_list_and_non_dict_items(self):
        for bad in (None, {}, "x", 3):
            with self.assertRaises(ValidationError):
                w.validate_widgets(bad)
        with self.assertRaises(ValidationError):
            w.validate_widgets(["kpi_total"])

    def test_maximum_of_30_widgets(self):
        ok = [widget(f"w{i}") for i in range(30)]
        self.assertEqual(len(w.validate_widgets(ok)), 30)
        with self.assertRaisesMessage(ValidationError, "no máximo 30"):
            w.validate_widgets(ok + [widget("extra")])

    def test_rejects_unknown_type_size_period_and_bad_ids(self):
        with self.assertRaisesMessage(ValidationError, "desconhecido"):
            w.validate_widgets([widget(type_="drop_table")])
        with self.assertRaisesMessage(ValidationError, "Tamanho"):
            w.validate_widgets([widget(size="huge")])
        with self.assertRaisesMessage(ValidationError, "Período"):
            w.validate_widgets([widget(type_="timeline", period=15)])
        for bad_id in ("", "a b", "x" * 41, "<script>", None, 5):
            with self.assertRaises(ValidationError):
                w.validate_widgets([{"id": bad_id, "type": "kpi_total", "size": "sm", "config": {}}])

    def test_rejects_duplicate_ids(self):
        with self.assertRaisesMessage(ValidationError, "repetidos"):
            w.validate_widgets([widget("a"), widget("a")])

    def test_limit_is_clamped_to_type_range(self):
        out = w.validate_widgets([widget("a", "ranking_members", limit=9999), widget("b", "ranking_members", limit=1)])
        self.assertEqual(out[0]["config"]["limit"], 100)
        self.assertEqual(out[1]["config"]["limit"], 3)
        with self.assertRaises(ValidationError):
            w.validate_widgets([widget("a", "ranking_members", limit="abc")])

    def test_options_not_supported_by_type_are_dropped(self):
        out = w.validate_widgets([widget("a", "kpi_total", period=7, limit=5, text="oi", filters={"genders": ["F"]})])
        self.assertEqual(out[0]["config"], {"filters": {"genders": ["F"]}})
        out = w.validate_widgets([widget("b", "note", period=7, filters={"genders": ["F"]}, text="Olá")])
        self.assertEqual(out[0]["config"], {"text": "Olá"})

    def test_filters_go_through_sanitize_voter_filters(self):
        dirty = {"genders": ["F", "X"], "registered_by_ids": ["nao-e-uuid"], "age_min": "abc", "cities": ["Campinas"], "evil": 1}
        out = w.validate_widgets([widget("a", "kpi_total", filters=dirty)])
        self.assertEqual(out[0]["config"]["filters"], {"genders": ["F"], "cities": ["Campinas"]})
        out = w.validate_widgets([widget("b", "kpi_total", filters={"genders": ["X"]})])
        self.assertNotIn("filters", out[0]["config"])
        with self.assertRaises(ValidationError):
            w.validate_widgets([widget("c", "kpi_total", filters="tudo")])

    def test_title_and_note_text_are_limited_and_plain(self):
        out = w.validate_widgets([widget("a", "note", text="linha 1\r\nlinha 2", title="  Meu   título  ")])
        self.assertEqual(out[0]["config"], {"text": "linha 1\nlinha 2", "title": "Meu título"})
        with self.assertRaises(ValidationError):
            w.validate_widgets([widget("b", "note", text="x" * (w.MAX_NOTE_LENGTH + 1))])
        with self.assertRaises(ValidationError):
            w.validate_widgets([widget("c", "kpi_total", title="x" * (w.MAX_WIDGET_TITLE + 1))])

    def test_note_text_is_kept_as_data_not_html(self):
        out = w.validate_widgets([widget("a", "note", text="<script>alert(1)</script>")])
        self.assertEqual(out[0]["config"]["text"], "<script>alert(1)</script>")  # escapado só na renderização

    def test_config_must_be_dict(self):
        with self.assertRaises(ValidationError):
            w.validate_widgets([{"id": "a", "type": "kpi_total", "size": "sm", "config": [1]}])
        out = w.validate_widgets([{"id": "a", "type": "kpi_total", "size": "sm"}])
        self.assertEqual(out[0]["config"], {})

    def test_parse_stored_widgets_is_tolerant(self):
        stored = [widget("a"), {"id": "b", "type": "inexistente"}, "lixo", widget("a"), {"id": "c", "type": "kpi_today", "size": "xx"}]
        out = w.parse_stored_widgets(stored)
        self.assertEqual([x["id"] for x in out], ["a", "c"])
        self.assertEqual(out[1]["size"], "sm")  # tamanho inválido volta ao padrão do tipo
        self.assertEqual(w.parse_stored_widgets(None), [])
        self.assertEqual(w.parse_stored_widgets({"a": 1}), [])

    def test_effective_values(self):
        self.assertEqual(w.effective_period(widget(type_="timeline", period=90)), 90)
        self.assertEqual(w.effective_period(widget(type_="timeline", period=5)), 30)
        self.assertEqual(w.effective_limit(widget(type_="ranking_members", limit=500)), 100)
        self.assertEqual(w.effective_limit(widget(type_="ranking_members")), 10)
        self.assertEqual(w.effective_limit(widget(type_="kpi_total")), 0)
        self.assertEqual(w.widget_title(widget(type_="kpi_total")), "Total de apoiadores")
        self.assertEqual(w.widget_title(widget(type_="kpi_total", title="Base")), "Base")

    def test_widget_data_key_ignores_title_size_and_unused_options(self):
        a = widget("a", "timeline", "lg", period=30, title="A")
        b = widget("b", "timeline", "full", period=30, title="B")
        c = widget("c", "timeline", "lg", period=7)
        self.assertEqual(w.widget_data_key(a), w.widget_data_key(b))
        self.assertNotEqual(w.widget_data_key(a), w.widget_data_key(c))


class PresetTests(SimpleTestCase):
    def test_there_are_four_presets(self):
        self.assertEqual(set(DASHBOARD_PRESET_KEYS), {"visao_geral", "equipe", "territorial", "comunicacao"})

    def test_every_preset_passes_validation_unchanged(self):
        for key in DASHBOARD_PRESET_KEYS:
            raw = preset_widgets(key)
            validated = w.validate_widgets(raw)
            self.assertEqual(validated, raw, key)
            self.assertLessEqual(len(raw), w.MAX_WIDGETS)

    def test_default_dashboard_shows_registrations_per_cabo_prominently(self):
        widgets = DASHBOARD_PRESETS["visao_geral"]["widgets"]
        ranking = next(x for x in widgets if x["type"] == "ranking_members")
        self.assertEqual(ranking["size"], "full")
        self.assertLessEqual(widgets.index(ranking), 5)

    def test_preset_widgets_returns_independent_copies(self):
        first = preset_widgets("equipe")
        first[0]["config"]["period"] = 365
        self.assertNotEqual(preset_widgets("equipe")[0]["config"].get("period"), 365)
