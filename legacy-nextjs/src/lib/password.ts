import bcrypt from "bcryptjs";
import { z } from "zod";

export async function hashPassword(plain: string): Promise<string> {
  return bcrypt.hash(plain, 12);
}

export async function verifyPassword(plain: string, hash: string): Promise<boolean> {
  return bcrypt.compare(plain, hash);
}

/** Regra de senha para usuários do painel */
export const passwordSchema = z
  .string()
  .min(8, "A senha deve ter pelo menos 8 caracteres")
  .max(72, "A senha deve ter no máximo 72 caracteres")
  .regex(/[A-Za-z]/, "A senha deve conter letras")
  .regex(/[0-9]/, "A senha deve conter números");

/** Gera uma senha provisória legível (ex.: para reset feito pelo admin) */
export function generateTempPassword(): string {
  const letters = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ";
  const digits = "23456789";
  const bytes = crypto.getRandomValues(new Uint8Array(10));
  let out = "";
  for (let i = 0; i < 8; i++) out += letters[bytes[i] % letters.length];
  out += digits[bytes[8] % digits.length] + digits[bytes[9] % digits.length];
  return out;
}
