"""Configuração do mapa territorial (modos, mapas base, enquadramento). Lógica pura, sem banco.

Tudo que o navegador precisa chega pelo `<script type="application/json" id="map-config">` da página
(veja `build_map_config`), então o JavaScript não duplica constantes do servidor.
"""

from __future__ import annotations

DEFAULT_MODE = "bairros"
DEFAULT_BASEMAP = "ruas"

# (valor, rótulo) — o valor é usado no localStorage do navegador
MAP_MODES: tuple[tuple[str, str], ...] = (("bairros", "Bairros"), ("pontos", "Pontos"), ("calor", "Calor"))

_OSM_LINK = '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a>'
_CARTO_LINK = '<a href="https://carto.com/attributions" target="_blank" rel="noopener noreferrer">CARTO</a>'

BASEMAPS: dict[str, dict] = {
    "ruas": {
        "label": "Ruas",
        "url": "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "attribution": f"&copy; {_OSM_LINK} contributors",
        "subdomains": "abc",
        "maxZoom": 19,
    },
    "claro": {
        "label": "Claro",
        "url": "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
        "attribution": f"&copy; {_OSM_LINK} &copy; {_CARTO_LINK}",
        "subdomains": "abcd",
        "maxZoom": 20,
    },
}

# Centro do Brasil (quando ainda não há eleitores com localização)
BRAZIL_CENTER: tuple[float, float] = (-14.235, -51.925)
BRAZIL_ZOOM = 4
# Zoom máximo ao enquadrar os dados (evita aproximar demais um único CEP)
FIT_MAX_ZOOM = 15
# Zoom ao focar um bairro pelo ranking
FOCUS_ZOOM = 14

# Gradiente da camada de calor (do claro ao intenso)
HEAT_GRADIENT: dict[float, str] = {0.2: "#a5b4fc", 0.4: "#6366f1", 0.6: "#4338ca", 0.8: "#f59e0b", 1.0: "#dc2626"}

# Parâmetros dos modos "Pontos" e "Calor"
HEAT_OPTIONS = {"radius": 22, "blur": 18, "maxZoom": 16, "minOpacity": 0.35}
CLUSTER_OPTIONS = {"maxClusterRadius": 56}


def build_map_config(*, data_url: str, voters_url: str, login_url: str) -> dict:
    """Configuração entregue ao JavaScript (via json_script)."""
    return {
        "dataUrl": data_url,
        "votersUrl": voters_url,
        "loginUrl": login_url,
        "modes": [{"value": value, "label": label} for value, label in MAP_MODES],
        "defaultMode": DEFAULT_MODE,
        "basemaps": BASEMAPS,
        "defaultBasemap": DEFAULT_BASEMAP,
        "center": list(BRAZIL_CENTER),
        "zoom": BRAZIL_ZOOM,
        "fitMaxZoom": FIT_MAX_ZOOM,
        "focusZoom": FOCUS_ZOOM,
        "heatGradient": {str(stop): color for stop, color in HEAT_GRADIENT.items()},
        "heatOptions": HEAT_OPTIONS,
        "clusterOptions": CLUSTER_OPTIONS,
    }
