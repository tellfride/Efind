// GET /api/painel/mapa/dados?{filtros de eleitores} — dados agregados do mapa territorial.
// Pontos individuais trazem apenas id e coordenadas aproximadas (nunca nome ou telefone).
import { NextResponse, type NextRequest } from "next/server";
import { authorize } from "@/lib/auth";
import { parseVoterFilters } from "@/lib/voter-filters";
import { loadMapData } from "@/server/map/data";

export const dynamic = "force-dynamic";

const NO_STORE = { "Cache-Control": "private, no-store" };

export async function GET(req: NextRequest) {
  const auth = await authorize("mapa", "view");
  if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status, headers: NO_STORE });

  // parseVoterFilters valida cada campo com zod e descarta valores inválidos
  const filters = parseVoterFilters(req.nextUrl.searchParams);
  try {
    const data = await loadMapData(auth.user, filters);
    return NextResponse.json(data, { headers: NO_STORE });
  } catch (err) {
    console.error("[mapa] falha ao carregar dados:", err instanceof Error ? err.message : "erro desconhecido");
    return NextResponse.json({ error: "Não foi possível carregar os dados do mapa." }, { status: 500, headers: NO_STORE });
  }
}
