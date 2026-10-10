// Detalhes expansíveis de um registro de auditoria (sem JS: <details>).
import { ChevronRight } from "lucide-react";

export function AuditDetails({ details }: { details: unknown }) {
  if (details === null || details === undefined) return <span className="text-slate-400">—</span>;
  if (typeof details === "object" && !Array.isArray(details) && Object.keys(details as object).length === 0) {
    return <span className="text-slate-400">—</span>;
  }
  return (
    <details className="group">
      <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-xs font-medium text-brand-700 select-none hover:underline [&::-webkit-details-marker]:hidden">
        <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" aria-hidden />
        Ver detalhes
      </summary>
      <pre className="mt-2 max-h-72 max-w-[calc(100vw-4rem)] overflow-auto rounded-lg bg-slate-900 p-3 text-xs leading-relaxed text-slate-100 sm:max-w-md">
        {JSON.stringify(details, null, 2)}
      </pre>
    </details>
  );
}
