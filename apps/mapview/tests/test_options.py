"""Configuração do mapa entregue ao navegador e garantias estáticas de segurança do front-end."""

import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.mapview.options import BASEMAPS, DEFAULT_BASEMAP, DEFAULT_MODE, MAP_MODES, build_map_config

ROOT = Path(settings.BASE_DIR)


class MapConfigTests(SimpleTestCase):
    def config(self):
        return build_map_config(data_url="/api/painel/mapa/dados/", voters_url="/painel/eleitores/", login_url="/login/")

    def test_is_json_serializable(self):
        self.assertEqual(json.loads(json.dumps(self.config()))["dataUrl"], "/api/painel/mapa/dados/")

    def test_modes(self):
        config = self.config()
        self.assertEqual([m["value"] for m in config["modes"]], ["bairros", "pontos", "calor"])
        self.assertEqual([m["label"] for m in config["modes"]], ["Bairros", "Pontos", "Calor"])
        self.assertEqual(config["defaultMode"], DEFAULT_MODE)
        self.assertEqual(DEFAULT_MODE, "bairros")
        self.assertEqual(len(MAP_MODES), 3)

    def test_basemaps_use_the_required_tile_servers_and_attribution(self):
        self.assertEqual(DEFAULT_BASEMAP, "ruas")
        osm, carto = BASEMAPS["ruas"], BASEMAPS["claro"]
        self.assertEqual(osm["url"], "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png")
        self.assertEqual(carto["url"], "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png")
        self.assertIn("OpenStreetMap", osm["attribution"])
        self.assertIn("contributors", osm["attribution"])
        self.assertIn("OpenStreetMap", carto["attribution"])
        self.assertIn("CARTO", carto["attribution"])
        for base in BASEMAPS.values():
            self.assertIn('rel="noopener noreferrer"', base["attribution"])

    def test_heat_gradient_keys_are_strings_for_json(self):
        gradient = self.config()["heatGradient"]
        self.assertTrue(all(isinstance(k, str) for k in gradient))
        self.assertEqual(max(float(k) for k in gradient), 1.0)


class FrontEndSafetyTests(SimpleTestCase):
    """Nada vindo do servidor pode virar HTML no navegador (bairros e nomes de equipe são texto digitado)."""

    FORBIDDEN_JS = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function")

    def test_map_js_never_builds_html_from_data(self):
        source = (ROOT / "static/js/mapview/map.js").read_text(encoding="utf-8")
        for token in self.FORBIDDEN_JS:
            self.assertFalse(token in source, f"uso proibido: {token}")

    def test_template_has_no_raw_html_sinks(self):
        source = (ROOT / "templates/mapview/index.html").read_text(encoding="utf-8")
        for token in ("x-html", "|safe", "mark_safe", "{% autoescape off"):
            self.assertFalse(token in source, f"uso proibido: {token}")

    def test_template_passes_data_with_json_script(self):
        source = (ROOT / "templates/mapview/index.html").read_text(encoding="utf-8")
        self.assertIn('|json_script:"map-config"', source)

    def test_vendored_libraries_exist(self):
        for name in ("leaflet.js", "leaflet.css", "leaflet.markercluster.js", "leaflet-heat.js", "MarkerCluster.css"):
            self.assertTrue((ROOT / "static/vendor/leaflet" / name).is_file(), name)
