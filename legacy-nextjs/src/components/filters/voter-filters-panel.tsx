"use client";

// Painel de filtros de eleitores compartilhado (lista, mapa, dashboards, público de disparos).
//  - <VoterFiltersPanel value onChange options />  → controlado (ex.: público do disparo, widget)
//  - <UrlVoterFilters options />                   → sincronizado com a URL (ex.: lista, mapa)
// As opções vêm do servidor: getVoterFilterOptions(user) em src/server/filter-options.ts.
import * as React from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Filter, RotateCcw, SlidersHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  GENDERS,
  GENDER_LABELS,
  SUPPORT_LEVELS,
  SUPPORT_LEVEL_LABELS,
  VOTER_SOURCES,
  VOTER_SOURCE_LABELS,
} from "@/lib/constants";
import {
  countActiveFilters,
  parseVoterFilters,
  voterFiltersToSearchParams,
  type VoterFilters,
} from "@/lib/voter-filters";
import type { VoterFilterOptions } from "@/server/filter-options";
import { Button } from "@/components/ui/button";
import { Checkbox, Input, Label, Select } from "@/components/ui/form";
import { MultiSelect } from "@/components/ui/multi-select";

export type VoterFilterField = keyof VoterFilters;

const ALL_FIELDS: VoterFilterField[] = [
  "q",
  "neighborhoods",
  "cities",
  "coordinatorIds",
  "registeredByIds",
  "supportLevels",
  "genders",
  "ageMin",
  "tags",
  "sources",
  "electoralZones",
  "createdFrom",
  "messageable",
  "hasGeo",
];

/** Campos exibidos sem expandir "Mais filtros" */
const PRIMARY: VoterFilterField[] = ["q", "neighborhoods", "cities", "registeredByIds"];

const genderOptions = GENDERS.map((g) => ({ value: g, label: GENDER_LABELS[g] }));
const supportOptions = SUPPORT_LEVELS.map((s) => ({ value: s, label: SUPPORT_LEVEL_LABELS[s] }));
const sourceOptions = VOTER_SOURCES.map((s) => ({ value: s, label: VOTER_SOURCE_LABELS[s] }));

export function VoterFiltersPanel({
  value,
  onChange,
  options,
  fields = ALL_FIELDS,
  hide = [],
  className,
  defaultExpanded = false,
}: {
  value: VoterFilters;
  onChange: (next: VoterFilters) => void;
  options: VoterFilterOptions;
  /** Campos a exibir (padrão: todos) */
  fields?: VoterFilterField[];
  /** Campos a esconder */
  hide?: VoterFilterField[];
  className?: string;
  defaultExpanded?: boolean;
}) {
  const [expanded, setExpanded] = React.useState(defaultExpanded);
  const visible = (f: VoterFilterField) =>
    fields.includes(f) &&
    !hide.includes(f) &&
    (expanded || PRIMARY.includes(f)) &&
    !(f === "coordinatorIds" && options.coordinators.length === 0) &&
    !(f === "electoralZones" && options.electoralZones.length === 0) &&
    !(f === "tags" && options.tags.length === 0) &&
    !(f === "registeredByIds" && options.members.length <= 1);

  const set = <K extends VoterFilterField>(key: K, v: VoterFilters[K] | undefined) => {
    const next = { ...value };
    if (v === undefined || v === "" || (Array.isArray(v) && v.length === 0)) delete next[key];
    else next[key] = v;
    onChange(next);
  };
  const num = (s: string) => (s === "" || !/^\d+$/.test(s) ? undefined : Number(s));
  const hasSecondary = fields.some((f) => !PRIMARY.includes(f) && !hide.includes(f));

  return (
    <div className={cn("space-y-3", className)}>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {visible("q") && (
          <div className="space-y-1.5">
            <Label htmlFor="vf-q">Buscar</Label>
            <Input
              id="vf-q"
              value={value.q ?? ""}
              onChange={(e) => set("q", e.target.value || undefined)}
              placeholder="Nome, telefone ou e-mail"
            />
          </div>
        )}
        {visible("neighborhoods") && (
          <div className="space-y-1.5">
            <Label htmlFor="vf-bairro">Bairros</Label>
            <MultiSelect
              id="vf-bairro"
              options={options.neighborhoods}
              value={value.neighborhoods ?? []}
              onChange={(v) => set("neighborhoods", v)}
              placeholder="Todos os bairros"
              searchPlaceholder="Buscar bairro..."
            />
          </div>
        )}
        {visible("cities") && (
          <div className="space-y-1.5">
            <Label htmlFor="vf-cidade">Cidades</Label>
            <MultiSelect id="vf-cidade" options={options.cities} value={value.cities ?? []} onChange={(v) => set("cities", v)} placeholder="Todas as cidades" />
          </div>
        )}
        {visible("coordinatorIds") && (
          <div className="space-y-1.5">
            <Label htmlFor="vf-coord">Coordenadores</Label>
            <MultiSelect
              id="vf-coord"
              options={options.coordinators}
              value={value.coordinatorIds ?? []}
              onChange={(v) => set("coordinatorIds", v)}
              placeholder="Todos"
            />
          </div>
        )}
        {visible("registeredByIds") && (
          <div className="space-y-1.5">
            <Label htmlFor="vf-cabo">Cadastrado por</Label>
            <MultiSelect
              id="vf-cabo"
              options={options.members}
              value={value.registeredByIds ?? []}
              onChange={(v) => set("registeredByIds", v)}
              placeholder="Toda a equipe"
              searchPlaceholder="Buscar membro..."
            />
          </div>
        )}
        {visible("supportLevels") && (
          <div className="space-y-1.5">
            <Label htmlFor="vf-apoio">Nível de apoio</Label>
            <MultiSelect
              id="vf-apoio"
              options={supportOptions}
              value={value.supportLevels ?? []}
              onChange={(v) => set("supportLevels", v as VoterFilters["supportLevels"])}
              placeholder="Todos"
            />
          </div>
        )}
        {visible("genders") && (
          <div className="space-y-1.5">
            <Label htmlFor="vf-genero">Gênero</Label>
            <MultiSelect
              id="vf-genero"
              options={genderOptions}
              value={value.genders ?? []}
              onChange={(v) => set("genders", v as VoterFilters["genders"])}
              placeholder="Todos"
            />
          </div>
        )}
        {visible("ageMin") && (
          <div className="space-y-1.5">
            <Label>Faixa de idade</Label>
            <div className="flex items-center gap-2">
              <Input
                type="number"
                inputMode="numeric"
                min={16}
                max={120}
                aria-label="Idade mínima"
                placeholder="De"
                value={value.ageMin ?? ""}
                onChange={(e) => set("ageMin", num(e.target.value))}
              />
              <span className="text-slate-400">–</span>
              <Input
                type="number"
                inputMode="numeric"
                min={16}
                max={120}
                aria-label="Idade máxima"
                placeholder="Até"
                value={value.ageMax ?? ""}
                onChange={(e) => set("ageMax", num(e.target.value))}
              />
            </div>
          </div>
        )}
        {visible("tags") && (
          <div className="space-y-1.5">
            <Label htmlFor="vf-tags">Tags</Label>
            <MultiSelect id="vf-tags" options={options.tags} value={value.tags ?? []} onChange={(v) => set("tags", v)} placeholder="Qualquer tag" />
          </div>
        )}
        {visible("sources") && (
          <div className="space-y-1.5">
            <Label htmlFor="vf-origem">Origem do cadastro</Label>
            <MultiSelect
              id="vf-origem"
              options={sourceOptions}
              value={value.sources ?? []}
              onChange={(v) => set("sources", v as VoterFilters["sources"])}
              placeholder="Todas"
            />
          </div>
        )}
        {visible("electoralZones") && (
          <div className="space-y-1.5">
            <Label htmlFor="vf-zona">Zona eleitoral</Label>
            <MultiSelect
              id="vf-zona"
              options={options.electoralZones}
              value={value.electoralZones ?? []}
              onChange={(v) => set("electoralZones", v)}
              placeholder="Todas"
            />
          </div>
        )}
        {visible("createdFrom") && (
          <div className="space-y-1.5">
            <Label>Cadastrados entre</Label>
            <div className="flex items-center gap-2">
              <Input type="date" aria-label="Data inicial" value={value.createdFrom ?? ""} onChange={(e) => set("createdFrom", e.target.value || undefined)} />
              <Input type="date" aria-label="Data final" value={value.createdTo ?? ""} onChange={(e) => set("createdTo", e.target.value || undefined)} />
            </div>
          </div>
        )}
        {visible("hasGeo") && (
          <div className="space-y-1.5">
            <Label htmlFor="vf-geo">Localização no mapa</Label>
            <Select
              id="vf-geo"
              value={value.hasGeo === undefined ? "" : value.hasGeo ? "1" : "0"}
              onChange={(e) => set("hasGeo", e.target.value === "" ? undefined : e.target.value === "1")}
            >
              <option value="">Todos</option>
              <option value="1">Com localização</option>
              <option value="0">Sem localização</option>
            </Select>
          </div>
        )}
        {visible("messageable") && (
          <div className="flex items-end pb-2">
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <Checkbox checked={value.messageable === true} onChange={(e) => set("messageable", e.target.checked ? true : undefined)} />
              Somente aptos a receber WhatsApp
            </label>
          </div>
        )}
      </div>
      {hasSecondary && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-600 hover:text-brand-700"
        >
          <SlidersHorizontal className="size-4" />
          {expanded ? "Menos filtros" : "Mais filtros"}
        </button>
      )}
    </div>
  );
}

/** Painel de filtros sincronizado com a URL (aplica ao clicar em "Filtrar"). Remove ?page ao aplicar. */
export function UrlVoterFilters({
  options,
  fields,
  hide,
  className,
}: {
  options: VoterFilterOptions;
  fields?: VoterFilterField[];
  hide?: VoterFilterField[];
  className?: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const current = React.useMemo(() => parseVoterFilters(new URLSearchParams(searchParams.toString())), [searchParams]);
  const [draft, setDraft] = React.useState<VoterFilters>(current);
  const [pending, startTransition] = React.useTransition();
  React.useEffect(() => setDraft(current), [current]);

  const apply = (filters: VoterFilters) => {
    const base = new URLSearchParams(searchParams.toString());
    base.delete("page");
    const sp = voterFiltersToSearchParams(filters, base);
    startTransition(() => router.push(`${pathname}${sp.size ? `?${sp}` : ""}`));
  };
  const active = countActiveFilters(current);

  return (
    <form
      className={cn("rounded-xl border border-slate-200 bg-white p-4 shadow-sm", className)}
      onSubmit={(e) => {
        e.preventDefault();
        apply(draft);
      }}
    >
      <VoterFiltersPanel value={draft} onChange={setDraft} options={options} fields={fields} hide={hide} />
      <div className="mt-4 flex flex-wrap items-center justify-end gap-2 border-t border-slate-100 pt-3">
        {active > 0 && (
          <span className="mr-auto inline-flex items-center gap-1 text-xs text-slate-500">
            <Filter className="size-3.5" /> {active} filtro(s) ativo(s)
          </span>
        )}
        {active > 0 && (
          <Button type="button" variant="ghost" size="sm" onClick={() => apply({})} disabled={pending}>
            <RotateCcw /> Limpar
          </Button>
        )}
        <Button type="submit" size="sm" loading={pending}>
          <Filter /> Filtrar
        </Button>
      </div>
    </form>
  );
}

/** Chips com os filtros ativos (somente leitura), ex.: resumo do público de um disparo */
export function VoterFiltersSummary({ filters, options }: { filters: VoterFilters; options?: VoterFilterOptions }) {
  const name = (list: { value: string; label: string }[] | undefined, v: string) => list?.find((o) => o.value === v)?.label ?? v;
  const chips: string[] = [];
  if (filters.q) chips.push(`Busca: “${filters.q}”`);
  if (filters.neighborhoods?.length) chips.push(`Bairros: ${filters.neighborhoods.join(", ")}`);
  if (filters.cities?.length) chips.push(`Cidades: ${filters.cities.join(", ")}`);
  if (filters.coordinatorIds?.length) chips.push(`Coordenadores: ${filters.coordinatorIds.map((v) => name(options?.coordinators, v)).join(", ")}`);
  if (filters.registeredByIds?.length) chips.push(`Cadastrado por: ${filters.registeredByIds.map((v) => name(options?.members, v)).join(", ")}`);
  if (filters.supportLevels?.length) chips.push(`Apoio: ${filters.supportLevels.map((s) => SUPPORT_LEVEL_LABELS[s]).join(", ")}`);
  if (filters.genders?.length) chips.push(`Gênero: ${filters.genders.map((g) => GENDER_LABELS[g]).join(", ")}`);
  if (filters.ageMin !== undefined || filters.ageMax !== undefined) chips.push(`Idade: ${filters.ageMin ?? "…"}–${filters.ageMax ?? "…"}`);
  if (filters.tags?.length) chips.push(`Tags: ${filters.tags.join(", ")}`);
  if (filters.sources?.length) chips.push(`Origem: ${filters.sources.map((s) => VOTER_SOURCE_LABELS[s]).join(", ")}`);
  if (filters.electoralZones?.length) chips.push(`Zonas: ${filters.electoralZones.join(", ")}`);
  if (filters.createdFrom || filters.createdTo) chips.push(`Cadastro: ${filters.createdFrom ?? "…"} a ${filters.createdTo ?? "…"}`);
  if (filters.hasGeo !== undefined) chips.push(filters.hasGeo ? "Com localização" : "Sem localização");
  if (filters.messageable) chips.push("Aptos a WhatsApp");
  if (!chips.length) return <span className="text-sm text-slate-500">Todos os eleitores</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {chips.map((c) => (
        <span key={c} className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-700">
          {c}
        </span>
      ))}
    </div>
  );
}
