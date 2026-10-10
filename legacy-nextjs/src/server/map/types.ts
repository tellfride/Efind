// Tipos do módulo Mapa territorial. Puro (sem banco): componentes cliente importam com "import type".

/** Bairro com ao menos um eleitor geolocalizado (círculo no mapa) */
export interface MapNeighborhood {
  /** Chave estável bairro+cidade (seleção e chaves React) */
  key: string;
  /** Nome do bairro (ou "Bairro não informado" quando known = false) */
  name: string;
  /** false quando os eleitores não informaram bairro (não há filtro por esse grupo) */
  known: boolean;
  city: string | null;
  /** Total de eleitores do bairro que atendem aos filtros */
  count: number;
  /** Quantos desses têm coordenadas */
  mapped: number;
  /** Centroide = média das coordenadas dos eleitores geolocalizados do bairro */
  lat: number;
  lng: number;
  /** Aptos a receber WhatsApp (consentimento + opt-in + sem descadastro) */
  messageable: number;
  /** Nível de apoio APOIADOR */
  supporters: number;
  /** Quem mais cadastrou no bairro (até 3) */
  topMembers: { name: string; count: number }[];
}

/** Bairro sem nenhum eleitor geolocalizado (não aparece no mapa) */
export interface MapNeighborhoodWithoutGeo {
  key: string;
  name: string;
  known: boolean;
  city: string | null;
  count: number;
}

/** Ponto individual — apenas id e coordenadas aproximadas (nunca nome/telefone) */
export interface MapPoint {
  id: string;
  lat: number;
  lng: number;
}

export interface MapTotals {
  voters: number;
  withGeo: number;
  withoutGeo: number;
  approximate: number;
}

export type MapBounds = [[number, number], [number, number]];

/** Resposta de GET /api/painel/mapa/dados */
export interface MapData {
  totals: MapTotals;
  neighborhoods: MapNeighborhood[];
  neighborhoodsWithoutGeo: MapNeighborhoodWithoutGeo[];
  points: MapPoint[];
  /** true quando há mais eleitores geolocalizados do que o limite de pontos (amostra uniforme) */
  truncated: boolean;
  bounds: MapBounds | null;
  /** Usuário tem eleitores.view (links para a lista/ficha) */
  canViewVoters: boolean;
}

/** Fila de geocodificação da campanha (card do ADMIN) */
export interface GeoQueueCounts {
  pending: number;
  failed: number;
}

/** Resultado de "Localizar pendentes agora" */
export interface GeocodeRunResult {
  processed: number;
  located: number;
  failed: number;
  remaining: number;
}
