"use client";

// Filtros do mapa: painel compartilhado sincronizado com a URL, recolhível no celular.
import * as React from "react";
import { useSearchParams } from "next/navigation";
import { ChevronDown, SlidersHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";
import { countActiveFilters, parseVoterFilters } from "@/lib/voter-filters";
import type { VoterFilterOptions } from "@/server/filter-options";
import { UrlVoterFilters } from "@/components/filters/voter-filters-panel";
import { Badge } from "@/components/ui/badge";

export function MapFilters({ options }: { options: VoterFilterOptions }) {
  const searchParams = useSearchParams();
  const qs = searchParams.toString();
  const [open, setOpen] = React.useState(false);

  const active = React.useMemo(() => {
    const { hasGeo: _ignored, ...filters } = parseVoterFilters(new URLSearchParams(qs));
    return countActiveFilters(filters);
  }, [qs]);

  // No celular, recolhe ao aplicar os filtros para mostrar o mapa
  React.useEffect(() => setOpen(false), [qs]);

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls="mapa-filtros"
        className="flex w-full items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-left shadow-sm transition-colors hover:bg-slate-50 lg:hidden"
      >
        <span className="flex items-center gap-2 text-sm font-medium text-slate-900">
          <SlidersHorizontal className="size-4 text-brand-600" aria-hidden />
          Filtros
          {active > 0 && <Badge tone="brand">{active} ativo(s)</Badge>}
        </span>
        <ChevronDown className={cn("size-4 text-slate-400 transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      <div id="mapa-filtros" className={cn(open ? "mt-2 block" : "hidden", "lg:mt-0 lg:block")}>
        <UrlVoterFilters options={options} hide={["hasGeo"]} />
      </div>
    </div>
  );
}
