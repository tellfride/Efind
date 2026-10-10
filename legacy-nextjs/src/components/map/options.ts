// Modos de visualização e mapas base do mapa territorial (puro, sem Leaflet).

export const MAP_MODES = ["bairros", "pontos", "calor"] as const;
export type MapMode = (typeof MAP_MODES)[number];
export const MAP_MODE_LABELS: Record<MapMode, string> = {
  bairros: "Bairros",
  pontos: "Pontos",
  calor: "Calor",
};

export const BASEMAP_KEYS = ["ruas", "claro"] as const;
export type Basemap = (typeof BASEMAP_KEYS)[number];

export interface BasemapConfig {
  label: string;
  url: string;
  attribution: string;
  subdomains: string;
  maxZoom: number;
}

export const BASEMAPS: Record<Basemap, BasemapConfig> = {
  ruas: {
    label: "Ruas",
    url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    subdomains: "abc",
    maxZoom: 19,
  },
  claro: {
    label: "Claro",
    url: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: "abcd",
    maxZoom: 20,
  },
};

/** Centro do Brasil (quando ainda não há eleitores com localização) */
export const BRAZIL_CENTER: [number, number] = [-14.235, -51.925];
export const BRAZIL_ZOOM = 4;
/** Zoom máximo ao enquadrar os dados (evita aproximar demais um único CEP) */
export const FIT_MAX_ZOOM = 15;
/** Zoom ao focar um bairro pelo ranking */
export const FOCUS_ZOOM = 14;

/** Seleção de um bairro para o mapa voar até ele e abrir o popup (nonce permite repetir o clique) */
export interface MapFocus {
  key: string;
  nonce: number;
}

export function isMapMode(value: unknown): value is MapMode {
  return typeof value === "string" && (MAP_MODES as readonly string[]).includes(value);
}

export function isBasemap(value: unknown): value is Basemap {
  return typeof value === "string" && (BASEMAP_KEYS as readonly string[]).includes(value);
}
