// Barreira rápida de autenticação (Edge). A autorização de verdade (papel, permissões, usuário ativo,
// campanha ativa) é feita no servidor em src/lib/auth.ts, consultando o banco a cada requisição.
import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE, verifySession } from "@/lib/session";

export async function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  const session = await verifySession(req.cookies.get(SESSION_COOKIE)?.value);
  if (session) return NextResponse.next();

  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ error: "Não autenticado" }, { status: 401 });
  }
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = `?next=${encodeURIComponent(pathname + search)}`;
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/painel/:path*", "/super/:path*", "/api/painel/:path*", "/api/super/:path*"],
};
