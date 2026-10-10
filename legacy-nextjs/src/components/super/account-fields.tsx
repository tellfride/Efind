"use client";

import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { Field, Input } from "@/components/ui/form";
import { maskPhoneInput } from "@/lib/phone";

type Errors = Record<string, string[] | undefined> | undefined;

/**
 * Campos de uma conta (nome, e-mail, telefone, senha opcional).
 * prefix = "admin" gera os nomes adminName, adminEmail... (formulário de criação de campanha).
 */
export function AccountFields({ errors, prefix = "", autoFocus }: { errors: Errors; prefix?: string; autoFocus?: boolean }) {
  const [showPassword, setShowPassword] = useState(false);
  const key = (k: string) => (prefix ? `${prefix}${k.charAt(0).toUpperCase()}${k.slice(1)}` : k);
  const id = (k: string) => `${prefix || "account"}-${k}`;

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="Nome completo" htmlFor={id("name")} error={errors?.[key("name")]} required className="sm:col-span-2">
        <Input
          id={id("name")}
          name={key("name")}
          maxLength={120}
          required
          autoComplete="off"
          autoFocus={autoFocus}
          aria-invalid={!!errors?.[key("name")]}
        />
      </Field>
      <Field label="E-mail de acesso" htmlFor={id("email")} hint="Será o login. Precisa ser único no E-Find." error={errors?.[key("email")]} required>
        <Input
          id={id("email")}
          name={key("email")}
          type="email"
          inputMode="email"
          maxLength={160}
          required
          autoComplete="off"
          aria-invalid={!!errors?.[key("email")]}
          placeholder="nome@exemplo.com.br"
        />
      </Field>
      <Field label="Telefone / WhatsApp" htmlFor={id("phone")} error={errors?.[key("phone")]}>
        <Input
          id={id("phone")}
          name={key("phone")}
          inputMode="tel"
          autoComplete="off"
          aria-invalid={!!errors?.[key("phone")]}
          onChange={(e) => (e.currentTarget.value = maskPhoneInput(e.currentTarget.value))}
          placeholder="(11) 98765-4321"
        />
      </Field>
      <Field
        label="Senha"
        htmlFor={id("password")}
        hint="Deixe em branco para gerar uma senha provisória automaticamente."
        error={errors?.[key("password")]}
        className="sm:col-span-2"
      >
        <div className="relative">
          <Input
            id={id("password")}
            name={key("password")}
            type={showPassword ? "text" : "password"}
            autoComplete="new-password"
            maxLength={72}
            aria-invalid={!!errors?.[key("password")]}
            className="pr-10"
            placeholder="Mínimo de 8 caracteres, com letras e números"
          />
          <button
            type="button"
            onClick={() => setShowPassword((v) => !v)}
            className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-slate-400 hover:text-slate-600"
            aria-label={showPassword ? "Ocultar senha" : "Mostrar senha"}
          >
            {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          </button>
        </div>
      </Field>
    </div>
  );
}
