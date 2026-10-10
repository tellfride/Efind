// Autenticação e autorização no servidor (Server Components, Server Actions e Route Handlers).
// Sempre recarrega o usuário do banco: permissões/desativação valem imediatamente.
import { cache } from "react";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { prisma } from "./db";
import { SESSION_COOKIE, SESSION_MAX_AGE_SECONDS, signSession, verifySession } from "./session";
import { can, resolvePermissions, type Action, type ModuleKey, type PermissionSet } from "./permissions";
import type { CampaignRole, Role } from "./constants";

export interface SessionCampaign {
  id: string;
  slug: string;
  candidateName: string;
  ballotName: string;
  ballotNumber: string | null;
  party: string | null;
  office: string;
  city: string | null;
  state: string | null;
  primaryColor: string;
  logoUrl: string | null;
  status: string;
}

export interface SessionUser {
  id: string;
  name: string;
  email: string;
  role: Role;
  campaignId: string | null;
  parentId: string | null;
  inviteCode: string;
  campaign: SessionCampaign | null;
  permissions: PermissionSet;
}

/** Usuário de campanha (ADMIN, COORDENADOR ou CABO) — campaignId garantido */
export interface CampaignUser extends SessionUser {
  role: CampaignRole;
  campaignId: string;
  campaign: SessionCampaign;
}

/** Usuário logado (ou null). Memoizado por requisição. */
export const getSessionUser = cache(async (): Promise<SessionUser | null> => {
  const store = await cookies();
  const payload = await verifySession(store.get(SESSION_COOKIE)?.value);
  if (!payload) return null;

  const user = await prisma.user.findUnique({
    where: { id: payload.sub },
    include: { campaign: true, permissions: true },
  });
  if (!user || !user.active || user.sessionVersion !== payload.sv) return null;
  if (user.role !== "SUPER_ADMIN" && (!user.campaign || user.campaign.status !== "ACTIVE")) return null;

  const rolePermissions =
    user.role === "COORDENADOR" || user.role === "CABO"
      ? await prisma.rolePermission.findMany({ where: { campaignId: user.campaignId!, role: user.role } })
      : [];

  const c = user.campaign;
  return {
    id: user.id,
    name: user.name,
    email: user.email,
    role: user.role as Role,
    campaignId: user.campaignId,
    parentId: user.parentId,
    inviteCode: user.inviteCode,
    campaign: c
      ? {
          id: c.id,
          slug: c.slug,
          candidateName: c.candidateName,
          ballotName: c.ballotName,
          ballotNumber: c.ballotNumber,
          party: c.party,
          office: c.office,
          city: c.city,
          state: c.state,
          primaryColor: c.primaryColor,
          logoUrl: c.logoUrl,
          status: c.status,
        }
      : null,
    permissions: resolvePermissions(user.role as Role, rolePermissions, user.permissions),
  };
});

export function isCampaignUser(user: SessionUser | null): user is CampaignUser {
  return !!user && user.role !== "SUPER_ADMIN" && !!user.campaignId && !!user.campaign;
}

// ---------- Páginas (Server Components): redirecionam ----------

export async function requireUser(): Promise<SessionUser> {
  const user = await getSessionUser();
  if (!user) redirect("/login");
  return user;
}

export async function requireSuperAdmin(): Promise<SessionUser> {
  const user = await requireUser();
  if (user.role !== "SUPER_ADMIN") redirect("/painel");
  return user;
}

export async function requireCampaignUser(): Promise<CampaignUser> {
  const user = await requireUser();
  if (!isCampaignUser(user)) redirect("/super");
  return user;
}

/** Exige permissão no módulo; sem permissão → /painel/sem-permissao */
export async function requirePermission(module: ModuleKey, action: Action = "view"): Promise<CampaignUser> {
  const user = await requireCampaignUser();
  if (!can(user.permissions, module, action)) redirect("/painel/sem-permissao");
  return user;
}

/** Apenas ADMIN da campanha (ex.: matriz de permissões — não delegável) */
export async function requireAdmin(): Promise<CampaignUser> {
  const user = await requireCampaignUser();
  if (user.role !== "ADMIN") redirect("/painel/sem-permissao");
  return user;
}

// ---------- Server Actions e Route Handlers: não redirecionam ----------

export type AuthorizeResult =
  | { ok: true; user: CampaignUser }
  | { ok: false; status: 401 | 403; error: string };

/**
 * Verifica sessão + permissão sem redirecionar.
 *   const auth = await authorize("eleitores", "create");
 *   if (!auth.ok) return actionError(auth.error);            // em Server Action
 *   if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status }); // em Route Handler
 */
export async function authorize(module: ModuleKey | "admin", action: Action = "view"): Promise<AuthorizeResult> {
  const user = await getSessionUser();
  if (!user) return { ok: false, status: 401, error: "Sessão expirada. Faça login novamente." };
  if (!isCampaignUser(user)) return { ok: false, status: 403, error: "Acesso restrito a usuários de campanha." };
  if (module === "admin") {
    if (user.role !== "ADMIN") return { ok: false, status: 403, error: "Apenas administradores podem fazer isso." };
    return { ok: true, user };
  }
  if (!can(user.permissions, module, action)) {
    return { ok: false, status: 403, error: "Você não tem permissão para esta ação." };
  }
  return { ok: true, user };
}

export type AuthorizeSuperResult = { ok: true; user: SessionUser } | { ok: false; status: 401 | 403; error: string };

export async function authorizeSuperAdmin(): Promise<AuthorizeSuperResult> {
  const user = await getSessionUser();
  if (!user) return { ok: false, status: 401, error: "Sessão expirada. Faça login novamente." };
  if (user.role !== "SUPER_ADMIN") return { ok: false, status: 403, error: "Acesso restrito ao super admin." };
  return { ok: true, user };
}

// ---------- Cookie de sessão ----------

export async function createSession(userId: string, sessionVersion: number): Promise<void> {
  const token = await signSession({ sub: userId, sv: sessionVersion });
  const store = await cookies();
  store.set(SESSION_COOKIE, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: SESSION_MAX_AGE_SECONDS,
  });
}

export async function destroySession(): Promise<void> {
  const store = await cookies();
  store.delete(SESSION_COOKIE);
}

/** Destino inicial após login */
export function homePathFor(role: Role): string {
  return role === "SUPER_ADMIN" ? "/super" : "/painel";
}
