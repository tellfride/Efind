// Padrão de retorno das Server Actions usadas com useActionState.
import type { ZodError } from "zod";

export type ActionResult<T = undefined> = {
  ok: boolean;
  message?: string;
  error?: string;
  fieldErrors?: Record<string, string[] | undefined>;
  data?: T;
};

export const initialActionResult: ActionResult = { ok: false };

export function actionOk<T = undefined>(message?: string, data?: T): ActionResult<T> {
  return { ok: true, message, data };
}

export function actionError(error: string, fieldErrors?: Record<string, string[] | undefined>): ActionResult<never> {
  return { ok: false, error, fieldErrors };
}

export function zodToActionError(err: ZodError): ActionResult<never> {
  const flat = err.flatten();
  return {
    ok: false,
    error: flat.formErrors[0] ?? "Verifique os campos destacados.",
    fieldErrors: flat.fieldErrors as Record<string, string[] | undefined>,
  };
}

/** Converte FormData em objeto simples (campos repetidos viram array) */
export function formDataToObject(fd: FormData): Record<string, string | string[]> {
  const out: Record<string, string | string[]> = {};
  for (const [key, value] of fd.entries()) {
    if (typeof value !== "string") continue;
    if (key.startsWith("$ACTION")) continue;
    const prev = out[key];
    if (prev === undefined) out[key] = value;
    else out[key] = Array.isArray(prev) ? [...prev, value] : [prev, value];
  }
  return out;
}
