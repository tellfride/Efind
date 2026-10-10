import Link from "next/link";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn, formatNumber } from "@/lib/utils";

/**
 * Paginação por link (Server Component). Mantém os demais parâmetros da URL.
 *   <Pagination page={2} pageSize={25} total={340} basePath="/painel/eleitores" searchParams={sp} />
 */
export function Pagination({
  page,
  pageSize,
  total,
  basePath,
  searchParams,
  className,
}: {
  page: number;
  pageSize: number;
  total: number;
  basePath: string;
  searchParams?: URLSearchParams | Record<string, string | string[] | undefined>;
  className?: string;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const href = (p: number) => {
    const sp = new URLSearchParams();
    if (searchParams instanceof URLSearchParams) searchParams.forEach((v, k) => sp.append(k, v));
    else if (searchParams)
      for (const [k, v] of Object.entries(searchParams)) {
        if (v === undefined) continue;
        (Array.isArray(v) ? v : [v]).forEach((item) => sp.append(k, item));
      }
    sp.set("page", String(p));
    return `${basePath}?${sp.toString()}`;
  };
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  const linkCls = "inline-flex h-8 items-center gap-1 rounded-md border border-slate-300 bg-white px-2.5 text-sm text-slate-700 hover:bg-slate-50";
  const disabledCls = "pointer-events-none opacity-40";
  return (
    <div className={cn("flex items-center justify-between gap-3 px-1 py-3 text-sm text-slate-500", className)}>
      <span>
        {formatNumber(from)}–{formatNumber(to)} de {formatNumber(total)}
      </span>
      <div className="flex items-center gap-2">
        <Link href={href(page - 1)} className={cn(linkCls, page <= 1 && disabledCls)} aria-disabled={page <= 1}>
          <ChevronLeft className="size-4" /> Anterior
        </Link>
        <span className="hidden sm:inline">
          Página {page} de {pages}
        </span>
        <Link href={href(page + 1)} className={cn(linkCls, page >= pages && disabledCls)} aria-disabled={page >= pages}>
          Próxima <ChevronRight className="size-4" />
        </Link>
      </div>
    </div>
  );
}

/** Lê ?page= com segurança */
export function parsePage(value: string | string[] | undefined): number {
  const n = Number(Array.isArray(value) ? value[0] : value);
  return Number.isInteger(n) && n > 0 ? n : 1;
}
