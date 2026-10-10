"use client";

// Grupo de endereço com preenchimento automático pelo CEP (GET /api/public/cep/{cep}).
// Usado no formulário público e nos formulários do painel. Os campos continuam editáveis.
import * as React from "react";
import { CheckCircle2, ExternalLink, Loader2, MapPin } from "lucide-react";
import { UFS } from "@/lib/constants";
import { cn } from "@/lib/utils";
import { Field, Input, Select } from "@/components/ui/form";
import { maskCepInput, normalizeCepInput } from "./voter-utils";

export interface AddressValues {
  cep: string;
  street: string;
  number: string;
  complement: string;
  neighborhood: string;
  city: string;
  state: string;
}

type LookupStatus = "idle" | "loading" | "found" | "notfound" | "error";

export function AddressFields({
  values,
  onChange,
  errors,
  required = false,
  inputClassName,
  idPrefix = "addr",
}: {
  values: AddressValues;
  onChange: (patch: Partial<AddressValues>) => void;
  errors?: Record<string, string[] | undefined>;
  /** Grupo obrigatório: CEP, bairro, cidade e UF */
  required?: boolean;
  inputClassName?: string;
  idPrefix?: string;
}) {
  const [status, setStatus] = React.useState<LookupStatus>("idle");
  const abortRef = React.useRef<AbortController | null>(null);
  const lastLookup = React.useRef<string>(normalizeCepInput(values.cep) ?? "");
  const numberRef = React.useRef<HTMLInputElement>(null);
  const id = (name: string) => `${idPrefix}-${name}`;
  const err = (name: string) => errors?.[name];

  React.useEffect(() => () => abortRef.current?.abort(), []);

  const lookup = async (cep: string) => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setStatus("loading");
    try {
      const res = await fetch(`/api/public/cep/${cep}`, { signal: ctrl.signal });
      if (res.status === 404 || res.status === 400) {
        setStatus("notfound");
        return;
      }
      if (!res.ok) {
        setStatus("error");
        return;
      }
      const info = (await res.json()) as { street?: string | null; neighborhood?: string | null; city?: string | null; state?: string | null };
      const patch: Partial<AddressValues> = {};
      if (info.street) patch.street = info.street;
      if (info.neighborhood) patch.neighborhood = info.neighborhood;
      if (info.city) patch.city = info.city;
      if (info.state) patch.state = info.state;
      onChange(patch);
      setStatus("found");
      // Rua já preenchida → próximo passo é o número
      if (info.street) setTimeout(() => numberRef.current?.focus(), 0);
    } catch (e) {
      if ((e as Error).name !== "AbortError") setStatus("error");
    }
  };

  const onCepChange = (raw: string) => {
    const masked = maskCepInput(raw);
    onChange({ cep: masked });
    const digits = normalizeCepInput(masked);
    if (!digits) {
      lastLookup.current = "";
      abortRef.current?.abort();
      setStatus("idle");
      return;
    }
    if (digits !== lastLookup.current) {
      lastLookup.current = digits;
      void lookup(digits);
    }
  };

  const text = (name: Exclude<keyof AddressValues, "cep" | "state">) => ({
    id: id(name),
    name,
    value: values[name],
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => onChange({ [name]: e.target.value } as Partial<AddressValues>),
    "aria-invalid": err(name) ? true : undefined,
    className: inputClassName,
  });

  return (
    <div className="space-y-4">
      <Field
        label="CEP"
        htmlFor={id("cep")}
        required={required}
        error={err("cep")}
        hint={
          status === "loading" ? (
            <span className="inline-flex items-center gap-1.5">
              <Loader2 className="size-3.5 animate-spin" aria-hidden /> Buscando endereço...
            </span>
          ) : status === "found" ? (
            <span className="inline-flex items-center gap-1.5 text-emerald-700">
              <CheckCircle2 className="size-3.5" aria-hidden /> Endereço preenchido pelo CEP. Confira e complete.
            </span>
          ) : status === "notfound" ? (
            <span className="text-amber-700">CEP não encontrado. Preencha o endereço abaixo.</span>
          ) : status === "error" ? (
            <span className="text-amber-700">Não foi possível consultar o CEP agora. Preencha o endereço abaixo.</span>
          ) : (
            <a
              href="https://buscacepinter.correios.com.br/app/endereco/index.php"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-brand-700 hover:underline"
            >
              Não sei meu CEP <ExternalLink className="size-3" aria-hidden />
            </a>
          )
        }
      >
        <div className="relative">
          <MapPin className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-slate-400" aria-hidden />
          <Input
            id={id("cep")}
            name="cep"
            inputMode="numeric"
            autoComplete="postal-code"
            placeholder="00000-000"
            value={values.cep}
            onChange={(e) => onCepChange(e.target.value)}
            aria-invalid={err("cep") ? true : undefined}
            className={cn("pl-9", inputClassName)}
            maxLength={9}
            required={required}
          />
        </div>
      </Field>

      <Field label="Rua / logradouro" htmlFor={id("street")} error={err("street")}>
        <Input {...text("street")} autoComplete="address-line1" maxLength={160} />
      </Field>

      <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-3">
        <Field label="Número" htmlFor={id("number")} error={err("number")}>
          <Input {...text("number")} ref={numberRef} inputMode="text" placeholder="Ex.: 120 ou s/n" maxLength={20} />
        </Field>
        <Field label="Complemento" htmlFor={id("complement")} error={err("complement")}>
          <Input {...text("complement")} autoComplete="address-line2" placeholder="Apto, bloco..." maxLength={80} />
        </Field>
      </div>

      <Field label="Bairro" htmlFor={id("neighborhood")} required={required} error={err("neighborhood")}>
        <Input {...text("neighborhood")} required={required} maxLength={100} />
      </Field>

      <div className="grid grid-cols-[minmax(0,1fr)_5.5rem] gap-3">
        <Field label="Cidade" htmlFor={id("city")} required={required} error={err("city")}>
          <Input {...text("city")} autoComplete="address-level2" required={required} maxLength={100} />
        </Field>
        <Field label="UF" htmlFor={id("state")} required={required} error={err("state")}>
          <Select
            id={id("state")}
            name="state"
            value={values.state}
            onChange={(e) => onChange({ state: e.target.value })}
            aria-invalid={err("state") ? true : undefined}
            className={inputClassName}
            required={required}
            autoComplete="address-level1"
          >
            <option value="">—</option>
            {UFS.map((uf) => (
              <option key={uf} value={uf}>
                {uf}
              </option>
            ))}
          </Select>
        </Field>
      </div>
    </div>
  );
}
