// Consulta pública de CEP (formulário de cadastro e formulários do painel). Com limite por IP.
import { NextResponse, type NextRequest } from "next/server";
import { lookupCep, normalizeCep } from "@/server/geo/cep";
import { rateLimit } from "@/lib/rate-limit";
import { getClientIp } from "@/lib/utils";

export async function GET(req: NextRequest, { params }: { params: Promise<{ cep: string }> }) {
  const { cep: raw } = await params;
  const cep = normalizeCep(raw);
  if (!cep) return NextResponse.json({ error: "CEP inválido" }, { status: 400 });

  const limit = rateLimit(`cep:${getClientIp(req.headers)}`, 60, 60_000);
  if (!limit.ok) {
    return NextResponse.json({ error: "Muitas consultas. Aguarde um instante." }, { status: 429, headers: { "Retry-After": String(limit.retryAfterSeconds) } });
  }

  const info = await lookupCep(cep);
  if (!info) return NextResponse.json({ error: "CEP não encontrado" }, { status: 404 });
  return NextResponse.json(info, { headers: { "Cache-Control": "public, max-age=86400" } });
}
