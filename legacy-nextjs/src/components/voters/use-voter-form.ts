"use client";

// Estado controlado dos formulários de eleitor + envio para Server Action sem o reset automático do React 19
// (o formulário mantém o que foi digitado quando o servidor devolve erros de validação).
import * as React from "react";
import type { ActionResult } from "@/lib/action-result";

export type FormValues = Record<string, string>;

export function useFormValues<T extends FormValues>(initial: T) {
  const [values, setValues] = React.useState<T>(initial);
  const set = React.useCallback((name: keyof T & string, value: string) => setValues((v) => ({ ...v, [name]: value })), []);
  const patch = React.useCallback((p: Partial<T>) => setValues((v) => ({ ...v, ...p })), []);
  return { values, set, patch, setValues };
}

/**
 * useActionState + envio via onSubmit (startTransition), devolvendo:
 *  - onSubmit: handler do <form>
 *  - state/pending: resultado e andamento da ação
 */
export function useVoterAction<R extends ActionResult<unknown>>(
  action: (prev: R, formData: FormData) => Promise<R>,
  initial: R,
) {
  const [state, dispatch, pending] = React.useActionState(action, initial);
  const onSubmit = React.useCallback(
    (e: React.FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      const fd = new FormData(e.currentTarget);
      React.startTransition(() => dispatch(fd));
    },
    [dispatch],
  );
  return { state, pending, onSubmit };
}

/** Leva o foco ao primeiro campo com erro quando o servidor devolve fieldErrors */
export function useFocusFirstError(state: ActionResult<unknown>, formRef: React.RefObject<HTMLFormElement | null>) {
  React.useEffect(() => {
    if (state.ok || !state.fieldErrors) return;
    const el = formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]');
    if (el) {
      el.focus({ preventScroll: true });
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [state, formRef]);
}

export function fieldError(state: ActionResult<unknown>, name: string): string[] | undefined {
  return state.ok ? undefined : state.fieldErrors?.[name];
}
