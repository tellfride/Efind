// Consulta de CEP (ViaCEP → BrasilAPI) com cache em CepCache.
// Puro Node + Prisma (sem next/*): pode ser usado pelo worker.
import { prisma } from "@/lib/db";

export interface CepInfo {
  cep: string; // 8 dígitos
  street: string | null;
  neighborhood: string | null;
  city: string | null;
  state: string | null;
}

export function normalizeCep(input: string | null | undefined): string | null {
  const d = (input ?? "").replace(/\D/g, "");
  return d.length === 8 && d !== "00000000" ? d : null;
}

export function formatCep(cep: string | null | undefined): string {
  const d = (cep ?? "").replace(/\D/g, "");
  return d.length === 8 ? `${d.slice(0, 5)}-${d.slice(5)}` : (cep ?? "");
}

const clean = (v: unknown): string | null => {
  if (typeof v !== "string") return null;
  const s = v.trim();
  return s ? s : null;
};

async function fetchJson(url: string, timeoutMs = 6000): Promise<unknown | null> {
  try {
    const res = await fetch(url, {
      signal: AbortSignal.timeout(timeoutMs),
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

async function fromViaCep(cep: string): Promise<CepInfo | null> {
  const data = (await fetchJson(`https://viacep.com.br/ws/${cep}/json/`)) as Record<string, unknown> | null;
  if (!data || data.erro) return null;
  return {
    cep,
    street: clean(data.logradouro),
    neighborhood: clean(data.bairro),
    city: clean(data.localidade),
    state: clean(data.uf),
  };
}

export interface BrasilApiCep extends CepInfo {
  latitude: number | null;
  longitude: number | null;
}

export async function fromBrasilApi(cep: string): Promise<BrasilApiCep | null> {
  const data = (await fetchJson(`https://brasilapi.com.br/api/cep/v2/${cep}`)) as Record<string, unknown> | null;
  if (!data || !data.cep) return null;
  const coords = (data.location as { coordinates?: { latitude?: string; longitude?: string } } | undefined)?.coordinates;
  const lat = coords?.latitude ? Number(coords.latitude) : NaN;
  const lng = coords?.longitude ? Number(coords.longitude) : NaN;
  return {
    cep,
    street: clean(data.street),
    neighborhood: clean(data.neighborhood),
    city: clean(data.city),
    state: clean(data.state),
    latitude: Number.isFinite(lat) && lat !== 0 ? lat : null,
    longitude: Number.isFinite(lng) && lng !== 0 ? lng : null,
  };
}

/** Endereço de um CEP (sem coordenadas). Retorna null se o CEP não existir/serviços indisponíveis. */
export async function lookupCep(input: string): Promise<CepInfo | null> {
  const cep = normalizeCep(input);
  if (!cep) return null;

  const cached = await prisma.cepCache.findUnique({ where: { cep } });
  if (cached && (cached.city || cached.street)) {
    return {
      cep,
      street: cached.street,
      neighborhood: cached.neighborhood,
      city: cached.city,
      state: cached.state,
    };
  }

  const info = (await fromViaCep(cep)) ?? (await fromBrasilApi(cep));
  if (!info) return null;
  await prisma.cepCache.upsert({
    where: { cep },
    create: { cep, street: info.street, neighborhood: info.neighborhood, city: info.city, state: info.state },
    update: { street: info.street, neighborhood: info.neighborhood, city: info.city, state: info.state },
  });
  return { cep, street: info.street, neighborhood: info.neighborhood, city: info.city, state: info.state };
}
