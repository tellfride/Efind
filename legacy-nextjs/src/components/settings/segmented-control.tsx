"use client";

import { cn } from "@/lib/utils";

/** Grupo de opções exclusivas (radio) com aparência de botões segmentados — envia `name` no formulário */
export function SegmentedControl<T extends string>({
  name,
  value,
  options,
  onChange,
  disabled,
  ariaLabel,
  className,
}: {
  name: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
  disabled?: boolean;
  ariaLabel: string;
  className?: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className={cn("inline-flex w-full rounded-lg bg-slate-100 p-1 sm:w-auto", disabled && "opacity-60", className)}
    >
      {options.map((opt) => {
        const id = `${name}-${opt.value}`;
        const active = opt.value === value;
        return (
          <label
            key={opt.value}
            htmlFor={id}
            className={cn(
              "flex-1 cursor-pointer rounded-md px-3 py-1.5 text-center text-xs font-medium whitespace-nowrap transition-colors sm:flex-none",
              "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-500",
              active ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-800",
              disabled && "cursor-not-allowed",
            )}
          >
            <input
              id={id}
              type="radio"
              name={name}
              value={opt.value}
              checked={active}
              disabled={disabled}
              onChange={() => onChange(opt.value)}
              className="sr-only"
            />
            {opt.label}
          </label>
        );
      })}
    </div>
  );
}
