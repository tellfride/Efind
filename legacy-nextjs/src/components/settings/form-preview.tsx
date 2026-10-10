"use client";

import { Lock } from "lucide-react";
import type { FormConfig } from "@/lib/constants";
import { DEFAULT_CONSENT_TEXT, DEFAULT_WHATSAPP_OPTIN_TEXT } from "@/lib/constants";
import { renderTemplate } from "@/lib/template-vars";
import { normalizeHexColor, readableTextColor } from "./settings-rules";

export interface PreviewBrand {
  ballotName: string;
  ballotNumber: string;
  party: string;
  primaryColor: string;
  logoUrl: string | null;
}

function FakeField({ label, required, wide }: { label: string; required: boolean; wide?: boolean }) {
  return (
    <div className={wide ? "col-span-2" : undefined}>
      <p className="text-[11px] font-medium text-slate-600">
        {label}
        {required ? <span className="ml-0.5 text-red-500">*</span> : <span className="ml-1 text-slate-400">(opcional)</span>}
      </p>
      <div className="mt-1 h-7 rounded-md border border-slate-200 bg-white" />
    </div>
  );
}

/** Pré-visualização do topo e dos campos do formulário público (reflete alterações ainda não salvas) */
export function FormPreview({
  brand,
  title,
  message,
  formConfig,
  consentText,
}: {
  brand: PreviewBrand;
  title: string;
  message: string;
  formConfig: FormConfig;
  consentText: string;
}) {
  const color = normalizeHexColor(brand.primaryColor) ?? "#4f46e5";
  const text = readableTextColor(color);
  const ballotName = brand.ballotName.trim() || "Nome de urna";
  const subtitle = [brand.ballotNumber.trim(), brand.party.trim()].filter(Boolean).join(" · ");
  const consent = renderTemplate(consentText.trim() || DEFAULT_CONSENT_TEXT, { candidato: ballotName });
  const shown = (key: keyof FormConfig) => formConfig[key] !== "hidden";
  const req = (key: keyof FormConfig) => formConfig[key] === "required";

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-slate-50 shadow-sm" aria-label="Pré-visualização do formulário público">
      <div className="px-5 pt-6 pb-10" style={{ backgroundColor: color, color: text }}>
        <div className="flex items-center gap-3">
          {brand.logoUrl ? (
            <img src={brand.logoUrl} alt="" className="size-12 shrink-0 rounded-xl bg-white object-contain p-1 shadow-sm" />
          ) : (
            <span
              className="flex size-12 shrink-0 items-center justify-center rounded-xl text-lg font-bold shadow-sm"
              style={{ backgroundColor: text === "#ffffff" ? "rgba(255,255,255,.18)" : "rgba(15,23,42,.08)" }}
              aria-hidden
            >
              {brand.ballotNumber.trim().slice(0, 2) || ballotName.slice(0, 1).toUpperCase()}
            </span>
          )}
          <div className="min-w-0">
            <p className="truncate text-base leading-tight font-bold">{ballotName}</p>
            {subtitle && <p className="truncate text-xs opacity-80">{subtitle}</p>}
          </div>
        </div>
        <p className="mt-5 text-lg leading-snug font-bold break-words">{title.trim() || `Faça parte da campanha de ${ballotName}`}</p>
        {message.trim() && <p className="mt-1.5 text-xs leading-relaxed whitespace-pre-line opacity-90 break-words">{message.trim()}</p>}
      </div>

      <div className="-mt-6 px-3 pb-4">
        <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="grid grid-cols-2 gap-3">
            <FakeField label="Nome completo" required wide />
            <FakeField label="WhatsApp" required wide />
            {shown("email") && <FakeField label="E-mail" required={req("email")} wide />}
            {shown("birthDate") && <FakeField label="Nascimento" required={req("birthDate")} />}
            {shown("gender") && <FakeField label="Gênero" required={req("gender")} />}
            {shown("address") && (
              <>
                <FakeField label="CEP" required={req("address")} />
                <FakeField label="Bairro" required={req("address")} />
              </>
            )}
            {shown("electoral") && (
              <>
                <FakeField label="Zona" required={req("electoral")} />
                <FakeField label="Seção" required={req("electoral")} />
              </>
            )}
          </div>
          <div className="space-y-2 border-t border-slate-100 pt-3">
            <div className="flex gap-2">
              <span className="mt-0.5 size-3.5 shrink-0 rounded border border-slate-300 bg-white" aria-hidden />
              <p className="line-clamp-4 text-[11px] leading-snug text-slate-600">{consent}</p>
            </div>
            <div className="flex gap-2">
              <span className="mt-0.5 size-3.5 shrink-0 rounded border border-slate-300 bg-white" aria-hidden />
              <p className="text-[11px] leading-snug text-slate-600">{DEFAULT_WHATSAPP_OPTIN_TEXT}</p>
            </div>
          </div>
          <div
            className="flex h-9 items-center justify-center rounded-lg text-xs font-semibold shadow-sm"
            style={{ backgroundColor: color, color: text }}
          >
            Quero participar
          </div>
          <p className="flex items-center justify-center gap-1 text-[10px] text-slate-400">
            <Lock className="size-3" aria-hidden /> Dados protegidos pela LGPD
          </p>
        </div>
      </div>
    </div>
  );
}
