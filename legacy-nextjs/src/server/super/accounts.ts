// Apoio às ações do super admin (servidor): códigos de convite únicos e erros de unicidade do Prisma.
import { Prisma } from "@prisma/client";
import { prisma } from "@/lib/db";
import { randomInviteCode } from "@/lib/crypto";

type Db = Prisma.TransactionClient | typeof prisma;

/** Gera um inviteCode que ainda não existe (o índice único é a garantia final) */
export async function uniqueInviteCode(db: Db, length = 8): Promise<string> {
  for (let attempt = 0; attempt < 10; attempt++) {
    const code = randomInviteCode(attempt < 5 ? length : length + 2);
    const taken = await db.user.findUnique({ where: { inviteCode: code }, select: { id: true } });
    if (!taken) return code;
  }
  throw new Error("Não foi possível gerar um código de convite único");
}

/** Erro de unicidade (P2002) envolvendo o campo informado */
export function isUniqueViolation(err: unknown, field: string): boolean {
  if (!(err instanceof Prisma.PrismaClientKnownRequestError) || err.code !== "P2002") return false;
  const target = (err.meta as { target?: unknown } | undefined)?.target;
  if (Array.isArray(target)) return target.some((t) => String(t).includes(field));
  if (typeof target === "string") return target.includes(field);
  return false;
}

/** Descrição segura de um erro para o log (sem argumentos da consulta, que podem conter dados pessoais) */
export function safeErrorTag(err: unknown): string {
  if (err instanceof Prisma.PrismaClientKnownRequestError) return `prisma:${err.code}`;
  if (err instanceof Error) return err.name;
  return "erro desconhecido";
}

export async function emailInUse(email: string): Promise<boolean> {
  const found = await prisma.user.findUnique({ where: { email }, select: { id: true } });
  return !!found;
}
