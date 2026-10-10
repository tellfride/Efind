"use client";

import { useActionState, useEffect, useRef } from "react";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FormMessage, Input } from "@/components/ui/form";
import { SubmitButton } from "@/components/ui/client";
import { initialActionResult } from "@/lib/action-result";
import { maskPhoneInput, formatPhone } from "@/lib/phone";
import { changePasswordAction, updateProfileAction } from "@/server/account/actions";

/** Formulário de troca de senha (usado em /painel/perfil e /super/perfil) */
export function ChangePasswordForm() {
  const [state, action] = useActionState(changePasswordAction, initialActionResult);
  const formRef = useRef<HTMLFormElement>(null);
  useEffect(() => {
    if (state.ok) {
      toast.success(state.message ?? "Senha alterada");
      formRef.current?.reset();
    }
  }, [state]);
  return (
    <Card>
      <form action={action} ref={formRef}>
        <CardHeader>
          <CardTitle>Alterar senha</CardTitle>
          <CardDescription>Ao trocar a senha, as sessões abertas em outros aparelhos são encerradas.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {!state.ok && <FormMessage result={state} />}
          <Field label="Senha atual" htmlFor="currentPassword" error={state.fieldErrors?.currentPassword} required>
            <Input id="currentPassword" name="currentPassword" type="password" autoComplete="current-password" required />
          </Field>
          <Field label="Nova senha" htmlFor="newPassword" hint="Mínimo de 8 caracteres, com letras e números." error={state.fieldErrors?.newPassword} required>
            <Input id="newPassword" name="newPassword" type="password" autoComplete="new-password" required />
          </Field>
          <Field label="Confirmar nova senha" htmlFor="confirmPassword" error={state.fieldErrors?.confirmPassword} required>
            <Input id="confirmPassword" name="confirmPassword" type="password" autoComplete="new-password" required />
          </Field>
        </CardContent>
        <CardFooter>
          <SubmitButton pendingText="Salvando...">Alterar senha</SubmitButton>
        </CardFooter>
      </form>
    </Card>
  );
}

/** Dados básicos do próprio usuário */
export function ProfileForm({ name, email, phone }: { name: string; email: string; phone: string | null }) {
  const [state, action] = useActionState(updateProfileAction, initialActionResult);
  useEffect(() => {
    if (state.ok) toast.success(state.message ?? "Perfil atualizado");
  }, [state]);
  return (
    <Card>
      <form action={action}>
        <CardHeader>
          <CardTitle>Dados pessoais</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {!state.ok && <FormMessage result={state} />}
          <Field label="Nome" htmlFor="name" error={state.fieldErrors?.name} required>
            <Input id="name" name="name" defaultValue={name} required />
          </Field>
          <Field label="E-mail" htmlFor="email" hint="Para alterar o e-mail de acesso, fale com o administrador.">
            <Input id="email" value={email} disabled readOnly />
          </Field>
          <Field label="Telefone / WhatsApp" htmlFor="phone" error={state.fieldErrors?.phone}>
            <Input
              id="phone"
              name="phone"
              inputMode="tel"
              defaultValue={formatPhone(phone)}
              onChange={(e) => (e.currentTarget.value = maskPhoneInput(e.currentTarget.value))}
              placeholder="(11) 98765-4321"
            />
          </Field>
        </CardContent>
        <CardFooter>
          <SubmitButton pendingText="Salvando...">Salvar</SubmitButton>
        </CardFooter>
      </form>
    </Card>
  );
}
