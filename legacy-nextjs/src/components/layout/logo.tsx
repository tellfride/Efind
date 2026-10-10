import { cn } from "@/lib/utils";

/** Marca E-Find: pino de mapa + lupa estilizados */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("size-8", className)} aria-hidden>
      <rect width="32" height="32" rx="8" className="fill-brand-600" />
      <path
        d="M16 6.5c-4.1 0-7.4 3.2-7.4 7.2 0 5.3 7.4 11.8 7.4 11.8s7.4-6.5 7.4-11.8c0-4-3.3-7.2-7.4-7.2Z"
        fill="none"
        stroke="white"
        strokeWidth="2.2"
        strokeLinejoin="round"
      />
      <circle cx="16" cy="13.6" r="2.9" fill="white" />
    </svg>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2 text-slate-900", className)}>
      <LogoMark />
      <span className="text-lg font-extrabold tracking-tight">
        E<span className="text-brand-500">-</span>Find
      </span>
    </span>
  );
}
