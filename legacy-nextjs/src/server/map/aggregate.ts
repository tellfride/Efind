// Agregação dos dados do mapa (pura, sem banco — testada em tests/map-aggregate.test.ts).
// Recebe as linhas mínimas dos eleitores já filtrados pelo escopo do usuário e monta
// totais, bairros (centroide), pontos (sem dados pessoais) e limites do mapa.
import type {
  MapBounds,
  MapData,
  MapNeighborhood,
  MapNeighborhoodWithoutGeo,
  MapPoint,
} from "./types";

/** Limite de pontos individuais enviados ao navegador */
export const MAP_POINT_LIMIT = 20000;
/** Quantos membros aparecem em "quem mais cadastrou" de cada bairro */
export const TOP_MEMBERS_PER_NEIGHBORHOOD = 3;
export const UNKNOWN_NEIGHBORHOOD = "Bairro não informado";
const UNKNOWN_MEMBER = "Membro da equipe";

/** Colunas mínimas lidas do banco para o mapa */
export interface MapVoterRow {
  id: string;
  latitude: number | null;
  longitude: number | null;
  geoStatus: string;
  neighborhood: string | null;
  city: string | null;
  supportLevel: string | null;
  whatsappOptIn: boolean;
  optOutAt: Date | null;
  consentAt: Date | null;
  registeredById: string;
}

export interface AggregateOptions {
  /** id → nome dos membros da equipe (para "quem mais cadastrou") */
  memberNames: ReadonlyMap<string, string>;
  canViewVoters: boolean;
  pointLimit?: number;
  topMembers?: number;
}

/** Mesmo critério de MESSAGEABLE_WHERE (src/server/access.ts) */
export function isMessageableRow(row: Pick<MapVoterRow, "whatsappOptIn" | "optOutAt" | "consentAt">): boolean {
  return row.whatsappOptIn === true && row.optOutAt === null && row.consentAt !== null;
}

/** Coordenadas utilizáveis (finitas, dentro do globo e diferentes de 0,0) */
export function validCoordinates(lat: number | null | undefined, lng: number | null | undefined): lat is number {
  if (lat === null || lat === undefined || lng === null || lng === undefined) return false;
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return false;
  if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return false;
  return !(lat === 0 && lng === 0);
}

function clean(value: string | null | undefined): string | null {
  const v = (value ?? "").trim().replace(/\s+/g, " ");
  return v ? v : null;
}

/** Chave bairro+cidade (separador de unidade — não aparece em nomes digitados) */
export function neighborhoodKey(name: string | null, city: string | null): string {
  return `${name ?? ""}\u001f${city ?? ""}`;
}

function round(value: number, digits: number): number {
  const f = 10 ** digits;
  return Math.round(value * f) / f;
}

/** Amostra uniforme (índices igualmente espaçados), preservando a ordem. Determinística. */
export function samplePoints<T>(items: readonly T[], limit: number): T[] {
  if (limit <= 0) return [];
  if (items.length <= limit) return items.slice();
  const out: T[] = [];
  const step = items.length / limit;
  for (let i = 0; i < limit; i++) out.push(items[Math.floor(i * step)]);
  return out;
}

interface Group {
  name: string | null;
  city: string | null;
  count: number;
  mapped: number;
  latSum: number;
  lngSum: number;
  messageable: number;
  supporters: number;
  members: Map<string, number>;
}

const byCountThenName = (a: { count: number; name: string }, b: { count: number; name: string }) =>
  b.count - a.count || a.name.localeCompare(b.name, "pt-BR");

export function aggregateMapData(rows: readonly MapVoterRow[], opts: AggregateOptions): MapData {
  const pointLimit = opts.pointLimit ?? MAP_POINT_LIMIT;
  const topN = opts.topMembers ?? TOP_MEMBERS_PER_NEIGHBORHOOD;

  const groups = new Map<string, Group>();
  const geocoded: MapPoint[] = [];
  let approximate = 0;
  let minLat = Infinity;
  let minLng = Infinity;
  let maxLat = -Infinity;
  let maxLng = -Infinity;

  for (const row of rows) {
    const name = clean(row.neighborhood);
    const city = clean(row.city);
    const key = neighborhoodKey(name, city);
    let g = groups.get(key);
    if (!g) {
      g = { name, city, count: 0, mapped: 0, latSum: 0, lngSum: 0, messageable: 0, supporters: 0, members: new Map() };
      groups.set(key, g);
    }
    g.count++;
    if (isMessageableRow(row)) g.messageable++;
    if (row.supportLevel === "APOIADOR") g.supporters++;
    g.members.set(row.registeredById, (g.members.get(row.registeredById) ?? 0) + 1);

    const lat = row.latitude;
    const lng = row.longitude;
    if (validCoordinates(lat, lng)) {
      const lngN = lng as number;
      g.mapped++;
      g.latSum += lat;
      g.lngSum += lngN;
      if (row.geoStatus === "APPROXIMATE") approximate++;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
      if (lngN < minLng) minLng = lngN;
      if (lngN > maxLng) maxLng = lngN;
      geocoded.push({ id: row.id, lat: round(lat, 5), lng: round(lngN, 5) });
    }
  }

  const neighborhoods: MapNeighborhood[] = [];
  const neighborhoodsWithoutGeo: MapNeighborhoodWithoutGeo[] = [];

  for (const [key, g] of groups) {
    const base = { key, name: g.name ?? UNKNOWN_NEIGHBORHOOD, known: g.name !== null, city: g.city, count: g.count };
    if (g.mapped === 0) {
      neighborhoodsWithoutGeo.push(base);
      continue;
    }
    const topMembers = [...g.members.entries()]
      .map(([id, count]) => ({ name: opts.memberNames.get(id) ?? UNKNOWN_MEMBER, count }))
      .sort(byCountThenName)
      .slice(0, topN);
    neighborhoods.push({
      ...base,
      mapped: g.mapped,
      lat: round(g.latSum / g.mapped, 6),
      lng: round(g.lngSum / g.mapped, 6),
      messageable: g.messageable,
      supporters: g.supporters,
      topMembers,
    });
  }
  neighborhoods.sort(byCountThenName);
  neighborhoodsWithoutGeo.sort(byCountThenName);

  const withGeo = geocoded.length;
  const bounds: MapBounds | null = withGeo
    ? [
        [round(minLat, 6), round(minLng, 6)],
        [round(maxLat, 6), round(maxLng, 6)],
      ]
    : null;

  return {
    totals: { voters: rows.length, withGeo, withoutGeo: rows.length - withGeo, approximate },
    neighborhoods,
    neighborhoodsWithoutGeo,
    points: samplePoints(geocoded, pointLimit),
    truncated: withGeo > pointLimit,
    bounds,
    canViewVoters: opts.canViewVoters,
  };
}
