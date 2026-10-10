"use client";

import { useState } from "react";
import { Field, Input, Select } from "@/components/ui/form";
import { OFFICE_LABELS, OFFICES, UFS, type Office } from "@/lib/constants";
import { DEFAULT_PRIMARY_COLOR, expectedBallotNumberLength } from "./campaign-rules";

export interface CampaignFieldValues {
  candidateName: string;
  ballotName: string;
  ballotNumber: string | null;
  party: string | null;
  office: string;
  city: string | null;
  state: string | null;
  electionYear: number;
  primaryColor: string;
  voterGoal: number | null;
}

type Errors = Record<string, string[] | undefined> | undefined;

const HEX = /^#[0-9a-fA-F]{6}$/;

/** Campos do candidato/campanha (criação e edição) */
export function CampaignFields({ defaults, errors }: { defaults?: Partial<CampaignFieldValues>; errors: Errors }) {
  const [office, setOffice] = useState<string>(defaults?.office ?? "");
  const [color, setColor] = useState<string>(defaults?.primaryColor ?? DEFAULT_PRIMARY_COLOR);
  const [colorText, setColorText] = useState<string>(defaults?.primaryColor ?? DEFAULT_PRIMARY_COLOR);

  const digits = office && (OFFICES as readonly string[]).includes(office) ? expectedBallotNumberLength(office as Office) : null;
  const numberHint = digits
    ? `${OFFICE_LABELS[office as Office]}: ${digits} dígitos.`
    : "Somente números (2 a 5 dígitos).";

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="Nome completo do candidato" htmlFor="candidateName" error={errors?.candidateName} required className="sm:col-span-2">
        <Input
          id="candidateName"
          name="candidateName"
          defaultValue={defaults?.candidateName ?? ""}
          maxLength={120}
          required
          autoComplete="off"
          aria-invalid={!!errors?.candidateName}
          placeholder="Ex.: Maria Aparecida da Silva"
        />
      </Field>

      <Field label="Nome de urna" htmlFor="ballotName" hint="Como o nome aparece na urna e no painel." error={errors?.ballotName} required>
        <Input
          id="ballotName"
          name="ballotName"
          defaultValue={defaults?.ballotName ?? ""}
          maxLength={60}
          required
          autoComplete="off"
          aria-invalid={!!errors?.ballotName}
          placeholder="Ex.: Professora Maria"
        />
      </Field>

      <Field label="Cargo" htmlFor="office" error={errors?.office} required>
        <Select
          id="office"
          name="office"
          value={office}
          onChange={(e) => setOffice(e.target.value)}
          required
          aria-invalid={!!errors?.office}
        >
          <option value="" disabled>
            Selecione o cargo
          </option>
          {OFFICES.map((o) => (
            <option key={o} value={o}>
              {OFFICE_LABELS[o]}
            </option>
          ))}
        </Select>
      </Field>

      <Field label="Número de urna" htmlFor="ballotNumber" hint={numberHint} error={errors?.ballotNumber}>
        <Input
          id="ballotNumber"
          name="ballotNumber"
          defaultValue={defaults?.ballotNumber ?? ""}
          inputMode="numeric"
          pattern="[0-9]*"
          maxLength={5}
          autoComplete="off"
          aria-invalid={!!errors?.ballotNumber}
          onChange={(e) => (e.currentTarget.value = e.currentTarget.value.replace(/\D/g, "").slice(0, 5))}
          placeholder={digits ? "0".repeat(digits) : "Ex.: 12345"}
        />
      </Field>

      <Field label="Partido" htmlFor="party" hint="Sigla do partido ou federação." error={errors?.party}>
        <Input
          id="party"
          name="party"
          defaultValue={defaults?.party ?? ""}
          maxLength={30}
          autoComplete="off"
          aria-invalid={!!errors?.party}
          placeholder="Ex.: PSD"
        />
      </Field>

      <Field label="Cidade" htmlFor="city" error={errors?.city}>
        <Input
          id="city"
          name="city"
          defaultValue={defaults?.city ?? ""}
          maxLength={80}
          autoComplete="off"
          aria-invalid={!!errors?.city}
          placeholder="Ex.: Campinas"
        />
      </Field>

      <Field label="UF" htmlFor="state" error={errors?.state}>
        <Select id="state" name="state" defaultValue={defaults?.state ?? ""} aria-invalid={!!errors?.state}>
          <option value="">—</option>
          {UFS.map((uf) => (
            <option key={uf} value={uf}>
              {uf}
            </option>
          ))}
        </Select>
      </Field>

      <Field label="Ano da eleição" htmlFor="electionYear" error={errors?.electionYear} required>
        <Input
          id="electionYear"
          name="electionYear"
          type="number"
          inputMode="numeric"
          min={2000}
          max={2100}
          defaultValue={defaults?.electionYear ?? new Date().getFullYear()}
          required
          aria-invalid={!!errors?.electionYear}
        />
      </Field>

      <Field
        label="Meta de cadastros"
        htmlFor="voterGoal"
        hint="Total de eleitores que a campanha pretende cadastrar (opcional)."
        error={errors?.voterGoal}
      >
        <Input
          id="voterGoal"
          name="voterGoal"
          type="number"
          inputMode="numeric"
          min={1}
          step={1}
          defaultValue={defaults?.voterGoal ?? ""}
          aria-invalid={!!errors?.voterGoal}
          placeholder="Ex.: 5000"
        />
      </Field>

      <Field label="Cor principal" htmlFor="primaryColorText" hint="Usada na identidade da campanha no painel." error={errors?.primaryColor}>
        <div className="flex items-center gap-2">
          <input
            type="color"
            aria-label="Escolher cor principal"
            value={color}
            onChange={(e) => {
              setColor(e.target.value);
              setColorText(e.target.value);
            }}
            className="h-10 w-12 shrink-0 cursor-pointer rounded-lg border border-slate-300 bg-white p-1"
          />
          <Input
            id="primaryColorText"
            value={colorText}
            maxLength={7}
            onChange={(e) => {
              const v = e.target.value.startsWith("#") ? e.target.value : `#${e.target.value}`;
              setColorText(v);
              if (HEX.test(v)) setColor(v.toLowerCase());
            }}
            onBlur={() => setColorText(color)}
            className="font-mono uppercase"
            aria-invalid={!!errors?.primaryColor}
          />
          <input type="hidden" name="primaryColor" value={color} />
        </div>
      </Field>
    </div>
  );
}
