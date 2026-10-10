"use client";

import { startTransition, useActionState, type FormEvent } from "react";
import type { ActionResult } from "@/lib/action-result";

/**
 * useActionState disparado no onSubmit: o React não limpa o formulário quando a ação devolve
 * erro de validação, então o usuário não perde o que digitou.
 */
export function useActionForm<T>(
  action: (prev: ActionResult<T>, formData: FormData) => Promise<ActionResult<T>>,
  initial: ActionResult<T> = { ok: false },
) {
  const [state, dispatch, pending] = useActionState(action, initial);
  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    startTransition(() => dispatch(formData));
  };
  return { state, onSubmit, pending };
}
