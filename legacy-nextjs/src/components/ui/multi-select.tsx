"use client";

import * as React from "react";
import { Check, ChevronDown, Search, X } from "lucide-react";
import { cn, normalizeText } from "@/lib/utils";

export interface MultiSelectOption {
  value: string;
  label: string;
  count?: number;
  hint?: string;
}

/** Seleção múltipla com busca (popover com checkboxes) */
export function MultiSelect({
  options,
  value,
  onChange,
  placeholder = "Selecione",
  searchPlaceholder = "Buscar...",
  emptyText = "Nenhuma opção",
  id,
  className,
  disabled,
}: {
  options: MultiSelectOption[];
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  id?: string;
  className?: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const ref = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const selected = new Set(value);
  const q = normalizeText(query);
  const filtered = q ? options.filter((o) => normalizeText(`${o.label} ${o.hint ?? ""}`).includes(q)) : options;
  const labelOf = (v: string) => options.find((o) => o.value === v)?.label ?? v;

  const toggle = (v: string) => onChange(selected.has(v) ? value.filter((x) => x !== v) : [...value, v]);

  return (
    <div className={cn("relative", className)} ref={ref}>
      <button
        type="button"
        id={id}
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className={cn(
          "flex min-h-10 w-full items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-left text-sm shadow-sm",
          "focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 focus:outline-none disabled:opacity-50",
        )}
      >
        <span className="flex min-w-0 flex-1 flex-wrap gap-1">
          {value.length === 0 && <span className="text-slate-400">{placeholder}</span>}
          {value.slice(0, 3).map((v) => (
            <span key={v} className="inline-flex max-w-full items-center gap-1 rounded bg-brand-50 px-1.5 py-0.5 text-xs text-brand-700">
              <span className="truncate">{labelOf(v)}</span>
              <span
                role="button"
                tabIndex={-1}
                aria-label={`Remover ${labelOf(v)}`}
                onClick={(e) => {
                  e.stopPropagation();
                  toggle(v);
                }}
                className="cursor-pointer rounded hover:bg-brand-100"
              >
                <X className="size-3" />
              </span>
            </span>
          ))}
          {value.length > 3 && <span className="text-xs text-slate-500">+{value.length - 3}</span>}
        </span>
        <ChevronDown className="size-4 shrink-0 text-slate-400" />
      </button>

      {open && (
        <div className="absolute z-50 mt-1 w-full min-w-56 rounded-lg border border-slate-200 bg-white shadow-lg">
          <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2">
            <Search className="size-4 text-slate-400" />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={searchPlaceholder}
              className="w-full bg-transparent text-sm outline-none placeholder:text-slate-400"
            />
          </div>
          <ul className="max-h-64 overflow-y-auto py-1 scrollbar-thin" role="listbox" aria-multiselectable>
            {filtered.length === 0 && <li className="px-3 py-2 text-sm text-slate-500">{emptyText}</li>}
            {filtered.map((o) => {
              const isOn = selected.has(o.value);
              return (
                <li key={o.value}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={isOn}
                    onClick={() => toggle(o.value)}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-slate-50"
                  >
                    <span
                      className={cn(
                        "flex size-4 shrink-0 items-center justify-center rounded border",
                        isOn ? "border-brand-600 bg-brand-600 text-white" : "border-slate-300",
                      )}
                    >
                      {isOn && <Check className="size-3" />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-slate-800">{o.label}</span>
                      {o.hint && <span className="block truncate text-xs text-slate-400">{o.hint}</span>}
                    </span>
                    {o.count !== undefined && <span className="text-xs text-slate-400 tabular-nums">{o.count}</span>}
                  </button>
                </li>
              );
            })}
          </ul>
          {value.length > 0 && (
            <div className="flex justify-between border-t border-slate-100 px-3 py-2 text-xs">
              <span className="text-slate-500">{value.length} selecionado(s)</span>
              <button type="button" className="font-medium text-brand-600 hover:underline" onClick={() => onChange([])}>
                Limpar
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
