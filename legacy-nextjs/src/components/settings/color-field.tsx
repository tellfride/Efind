"use client";

import { Check } from "lucide-react";
import { Field, Input } from "@/components/ui/form";
import { cn } from "@/lib/utils";
import { contrastRatio, normalizeHexColor, readableTextColor } from "./settings-rules";

const SWATCHES = [
  { hex: "#4f46e5", name: "Índigo" },
  { hex: "#2563eb", name: "Azul" },
  { hex: "#0e7490", name: "Petróleo" },
  { hex: "#15803d", name: "Verde" },
  { hex: "#ca8a04", name: "Amarelo" },
  { hex: "#ea580c", name: "Laranja" },
  { hex: "#dc2626", name: "Vermelho" },
  { hex: "#be185d", name: "Magenta" },
  { hex: "#7c3aed", name: "Roxo" },
  { hex: "#0f172a", name: "Grafite" },
];

/**
 * Cor principal: seletor nativo + texto hexadecimal (#RRGGBB) com amostras e pré-visualização.
 * `value` é o texto digitado (pode estar incompleto); `onChange` recebe o texto bruto.
 */
export function ColorField({
  value,
  onChange,
  error,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  error?: string[];
  disabled?: boolean;
}) {
  const valid = normalizeHexColor(value);
  const shown = valid ?? "#4f46e5";
  const lowContrast = valid ? readableTextColor(valid) !== "#ffffff" : false;
  const weakOnWhite = valid ? contrastRatio(valid, "#ffffff") < 3 : false;
  const invalidMessage = !valid && value.trim() !== "" ? ["Use o formato #RRGGBB (ex.: #4f46e5)"] : undefined;

  return (
    <Field
      label="Cor principal"
      htmlFor="primaryColor"
      required
      error={error ?? invalidMessage}
      hint={
        lowContrast
          ? "Cor clara: no formulário os textos sobre ela ficarão escuros para manter a leitura."
          : weakOnWhite
            ? "Atenção: esta cor tem pouco contraste com fundos brancos."
            : "Usada no topo e nos botões do formulário público e nos materiais da campanha."
      }
    >
      <div className="flex items-center gap-2">
        <label
          className={cn(
            "relative size-10 shrink-0 cursor-pointer overflow-hidden rounded-lg border border-slate-300 shadow-sm",
            disabled && "cursor-not-allowed opacity-60",
          )}
          style={{ backgroundColor: shown }}
          title="Escolher cor"
        >
          <span className="sr-only">Escolher cor no seletor</span>
          <input
            type="color"
            value={shown}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
            className="absolute inset-0 size-full cursor-pointer opacity-0"
          />
        </label>
        <Input
          id="primaryColor"
          name="primaryColor"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onBlur={() => {
            const n = normalizeHexColor(value);
            if (n && n !== value) onChange(n);
          }}
          maxLength={7}
          spellCheck={false}
          autoComplete="off"
          placeholder="#4f46e5"
          className="w-32 font-mono uppercase"
          aria-invalid={!valid || !!error?.length}
          disabled={disabled}
        />
      </div>
      <div className="flex flex-wrap gap-1.5 pt-1" role="group" aria-label="Sugestões de cor">
        {SWATCHES.map((s) => {
          const active = valid === s.hex;
          return (
            <button
              key={s.hex}
              type="button"
              disabled={disabled}
              onClick={() => onChange(s.hex)}
              className={cn(
                "flex size-7 items-center justify-center rounded-full ring-offset-2 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500",
                active ? "ring-2 ring-slate-400" : "hover:scale-110",
                disabled && "cursor-not-allowed",
              )}
              style={{ backgroundColor: s.hex }}
              title={s.name}
              aria-label={`Usar cor ${s.name}`}
              aria-pressed={active}
            >
              {active && <Check className="size-3.5" style={{ color: readableTextColor(s.hex) }} aria-hidden />}
            </button>
          );
        })}
      </div>
    </Field>
  );
}
