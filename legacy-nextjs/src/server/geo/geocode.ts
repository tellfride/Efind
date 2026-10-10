// Geocodificação de eleitores para o mapa. Coordenadas no nível do CEP/logradouro (não do imóvel),
// o que também protege a privacidade do eleitor.
// Ordem: cache → BrasilAPI (coordenadas do CEP) → Nominatim (rua) → Nominatim (CEP) → Nominatim (bairro) → cidade.
// Puro Node + Prisma (sem next/*): usado pelo worker e após cadastros.
import { prisma } from "@/lib/db";
import { slugify } from "@/lib/utils";
import { fromBrasilApi, normalizeCep } from "./cep";

export type GeoPrecision = "OK" | "APPROXIMATE";
export interface GeoPoint {
  latitude: number;
  longitude: number;
  precision: GeoPrecision;
  source: string;
}

export interface AddressInput {
  cep?: string | null;
  street?: string | null;
  neighborhood?: string | null;
  city?: string | null;
  state?: string | null;
}

// ---- Nominatim: no máximo 1 requisição por segundo (política de uso do OSM) ----
let nominatimChain: Promise<unknown> = Promise.resolve();
let lastNominatimAt = 0;

function userAgent() {
  return process.env.GEOCODER_USER_AGENT ?? "E-Find/1.0 (contato@efind.com.br)";
}

async function nominatim(params: Record<string, string>): Promise<{ lat: number; lng: number } | null> {
  const run = async () => {
    const wait = Math.max(0, lastNominatimAt + 1100 - Date.now());
    if (wait) await new Promise((r) => setTimeout(r, wait));
    lastNominatimAt = Date.now();
    const sp = new URLSearchParams({ format: "jsonv2", limit: "1", countrycodes: "br", ...params });
    try {
      const res = await fetch(`https://nominatim.openstreetmap.org/search?${sp}`, {
        headers: { "User-Agent": userAgent(), "Accept-Language": "pt-BR" },
        signal: AbortSignal.timeout(8000),
        cache: "no-store",
      });
      if (!res.ok) return null;
      const data = (await res.json()) as Array<{ lat: string; lon: string }>;
      if (!data.length) return null;
      const lat = Number(data[0].lat);
      const lng = Number(data[0].lon);
      return Number.isFinite(lat) && Number.isFinite(lng) ? { lat, lng } : null;
    } catch {
      return null;
    }
  };
  const p = nominatimChain.then(run, run);
  nominatimChain = p.catch(() => null);
  return p;
}

function areaKey(city: string, state: string | null | undefined, neighborhood?: string | null) {
  return `A:${slugify(state ?? "")}:${slugify(city)}${neighborhood ? `:${slugify(neighborhood)}` : ""}`;
}

async function cachedPoint(key: string): Promise<GeoPoint | null | undefined> {
  const row = await prisma.cepCache.findUnique({ where: { cep: key } });
  if (!row || !row.geoSource) return undefined; // nunca tentado
  if (row.latitude === null || row.longitude === null) return null; // tentado e falhou
  return {
    latitude: row.latitude,
    longitude: row.longitude,
    precision: row.geoSource === "brasilapi" || row.geoSource === "nominatim" ? "OK" : "APPROXIMATE",
    source: row.geoSource,
  };
}

async function savePoint(key: string, point: GeoPoint | null, address?: AddressInput) {
  const data = {
    latitude: point?.latitude ?? null,
    longitude: point?.longitude ?? null,
    geoSource: point?.source ?? "none",
  };
  await prisma.cepCache.upsert({
    where: { cep: key },
    create: {
      cep: key,
      ...data,
      street: address?.street ?? null,
      neighborhood: address?.neighborhood ?? null,
      city: address?.city ?? null,
      state: address?.state ?? null,
    },
    update: data,
  });
}

/** Coordenadas de um bairro (ou cidade, se neighborhood vazio), com cache */
async function geocodeArea(city: string, state: string | null | undefined, neighborhood?: string | null): Promise<GeoPoint | null> {
  const key = areaKey(city, state, neighborhood);
  const cached = await cachedPoint(key);
  if (cached !== undefined) return cached;
  const q = [neighborhood, city, state, "Brasil"].filter(Boolean).join(", ");
  const r = await nominatim({ q });
  const point: GeoPoint | null = r
    ? { latitude: r.lat, longitude: r.lng, precision: "APPROXIMATE", source: neighborhood ? "nominatim-bairro" : "nominatim-cidade" }
    : null;
  await savePoint(key, point, { city, state, neighborhood });
  return point;
}

/** Geocodifica um endereço. Retorna null se nada for encontrado. */
export async function geocodeAddress(addr: AddressInput): Promise<GeoPoint | null> {
  const cep = normalizeCep(addr.cep);

  if (cep) {
    const cached = await cachedPoint(cep);
    if (cached) return cached;
    if (cached === undefined) {
      let point: GeoPoint | null = null;
      const br = await fromBrasilApi(cep);
      if (br?.latitude !== null && br?.latitude !== undefined && br.longitude !== null) {
        point = { latitude: br.latitude, longitude: br.longitude, precision: "OK", source: "brasilapi" };
      }
      const street = addr.street ?? br?.street;
      const city = addr.city ?? br?.city;
      const state = addr.state ?? br?.state;
      if (!point && street && city) {
        const r = await nominatim({ street, city, state: state ?? "", country: "Brasil" });
        if (r) point = { latitude: r.lat, longitude: r.lng, precision: "OK", source: "nominatim" };
      }
      if (!point) {
        const r = await nominatim({ postalcode: `${cep.slice(0, 5)}-${cep.slice(5)}`, country: "Brasil" });
        if (r) point = { latitude: r.lat, longitude: r.lng, precision: "OK", source: "nominatim" };
      }
      await savePoint(cep, point, {
        street: street ?? null,
        neighborhood: addr.neighborhood ?? br?.neighborhood ?? null,
        city: city ?? null,
        state: state ?? null,
      });
      if (point) return point;
    }
  }

  if (addr.city && addr.neighborhood) {
    const p = await geocodeArea(addr.city, addr.state, addr.neighborhood);
    if (p) return p;
  }
  if (addr.city) return geocodeArea(addr.city, addr.state);
  return null;
}

/** Geocodifica um eleitor e grava latitude/longitude/geoStatus */
export async function geocodeVoter(voterId: string): Promise<void> {
  const voter = await prisma.voter.findUnique({
    where: { id: voterId },
    select: { id: true, cep: true, street: true, neighborhood: true, city: true, state: true },
  });
  if (!voter) return;
  const point = await geocodeAddress(voter);
  await prisma.voter.update({
    where: { id: voter.id },
    data: point
      ? { latitude: point.latitude, longitude: point.longitude, geoStatus: point.precision }
      : { geoStatus: "FAILED" },
  });
}

/** Processa eleitores com geoStatus PENDING (usado pelo worker). Retorna quantos processou. */
export async function processPendingGeocoding(limit = 10): Promise<number> {
  const pending = await prisma.voter.findMany({
    where: { geoStatus: "PENDING" },
    orderBy: { createdAt: "asc" },
    take: limit,
    select: { id: true },
  });
  for (const v of pending) {
    try {
      await geocodeVoter(v.id);
    } catch (err) {
      console.error("[geocode] falha", v.id, err);
      await prisma.voter.update({ where: { id: v.id }, data: { geoStatus: "FAILED" } }).catch(() => null);
    }
  }
  return pending.length;
}
