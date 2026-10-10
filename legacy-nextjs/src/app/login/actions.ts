"use server";

import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { z } from "zod";
import { prisma } from "@/lib/db";
import { createSession, destroySession, getSessionUser, homePathFor } from "@/lib/auth";
import { verifyPassword } from "@/lib/password";
import { rateLimit } from "@/lib/rate-limit";
import { audit } from "@/lib/audit";
import { getClientIp } from "@/lib/utils";
import type { ActionResult } from "@/lib/action-result";
import type { Role } from "@/lib/constants";

const loginSchema = z.object({
  email: z.string().trim().toLowerCase().email("Informe um e-mail válido"),
  password: z.string().min(1, "Informe a senha"),
  next: z.string().optional(),
});

// Hash fictício para igualar o tempo de resposta quando o e-mail não existe
const DUMMY_HASH = "$2b$12$K4J1uLqrHIAR1J6MXfIYV.8P3zKQuQ838m5/iT8AgPwR/zl9vs.Qm";

export async function loginAction(_prev: ActionResult, formData: FormData): Promise<ActionResult> {
  const parsed = loginSchema.safeParse({
    email: formData.get("email"),
    password: formData.get("password"),
    next: formData.get("next") || undefined,
  });
  if (!parsed.success) {
    return { ok: false, error: "Verifique os campos.", fieldErrors: parsed.error.flatten().fieldErrors };
  }
  const { email, password, next } = parsed.data;
  const ip = getClientIp(await headers());

  const limit = rateLimit(`login:${ip}:${email}`, 8, 15 * 60_000);
  const ipLimit = rateLimit(`login-ip:${ip}`, 40, 15 * 60_000);
  if (!limit.ok || !ipLimit.ok) {
    return { ok: false, error: `Muitas tentativas. Tente novamente em ${Math.ceil(Math.max(limit.retryAfterSeconds, ipLimit.retryAfterSeconds) / 60)} min.` };
  }

  const user = await prisma.user.findUnique({ where: { email }, include: { campaign: { select: { status: true } } } });
  const valid = await verifyPassword(password, user?.passwordHash ?? DUMMY_HASH);
  if (!user || !valid) {
    await audit({ action: "auth.login_failed", campaignId: user?.campaignId, userId: user?.id, details: { email }, ip });
    return { ok: false, error: "E-mail ou senha incorretos." };
  }
  if (!user.active) return { ok: false, error: "Seu acesso está desativado. Fale com o administrador da campanha." };
  if (user.role !== "SUPER_ADMIN" && user.campaign?.status !== "ACTIVE") {
    return { ok: false, error: "Esta campanha está suspensa. Fale com o suporte do E-Find." };
  }

  await prisma.user.update({ where: { id: user.id }, data: { lastLoginAt: new Date() } });
  await createSession(user.id, user.sessionVersion);
  await audit({ action: "auth.login", campaignId: user.campaignId, userId: user.id, ip });

  const home = homePathFor(user.role as Role);
  const safeNext = next && next.startsWith("/") && !next.startsWith("//") && next.startsWith(home) ? next : home;
  redirect(safeNext);
}

export async function logoutAction(): Promise<void> {
  const user = await getSessionUser();
  if (user) await audit({ action: "auth.logout", campaignId: user.campaignId, userId: user.id });
  await destroySession();
  redirect("/login");
}
