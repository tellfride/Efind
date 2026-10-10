"use client";

import { KeyRound, ShieldAlert } from "lucide-react";
import { CopyButton } from "@/components/ui/client";
import type { IssuedCredentials } from "@/server/super/validation";

/** Credenciais exibidas UMA vez (criação de usuário ou redefinição de senha) */
export function CredentialsPanel({ credentials }: { credentials: IssuedCredentials }) {
  const all = [
    `Acesso ao E-Find`,
    `Endereço: ${credentials.loginUrl}`,
    `E-mail: ${credentials.email}`,
    `Senha${credentials.generated ? " provisória" : ""}: ${credentials.password}`,
  ].join("\n");

  const rows = [
    { label: "Endereço de acesso", value: credentials.loginUrl, mono: false },
    { label: "E-mail", value: credentials.email, mono: false },
    { label: credentials.generated ? "Senha provisória" : "Senha", value: credentials.password, mono: true },
  ];

  return (
    <div className="space-y-4">
      <div className="flex gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900" role="alert">
        <ShieldAlert className="mt-0.5 size-5 shrink-0 text-amber-600" aria-hidden />
        <div>
          <p className="font-semibold">Anote ou copie agora: a senha não será exibida novamente.</p>
          <p className="mt-0.5 text-amber-800">
            Envie as credenciais por um canal seguro e oriente {credentials.name.split(" ")[0] || "o usuário"} a trocar a senha
            no primeiro acesso, em <strong>Meu perfil</strong>.
          </p>
        </div>
      </div>

      <dl className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
        {rows.map((row) => (
          <div key={row.label} className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <dt className="text-xs font-medium text-slate-500">{row.label}</dt>
              <dd className={row.mono ? "font-mono text-base font-semibold tracking-wide text-slate-900" : "text-sm break-all text-slate-900"}>
                {row.value}
              </dd>
            </div>
            <CopyButton value={row.value} size="sm" label="Copiar" className="self-start sm:self-auto" />
          </div>
        ))}
      </dl>

      <CopyButton value={all} label={<>Copiar tudo</>} className="w-full sm:w-auto" />
      <p className="flex items-center gap-1.5 text-xs text-slate-500">
        <KeyRound className="size-3.5" aria-hidden /> Por segurança, o E-Find guarda apenas o hash da senha.
      </p>
    </div>
  );
}
