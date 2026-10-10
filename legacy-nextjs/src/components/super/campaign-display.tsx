// Componentes de exibição de campanhas (sem estado — podem ser usados em Server Components).
import Link from "next/link";
import { ArrowLeft, ChevronRight, MapPin, Users, UsersRound } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Table, TBody, TD, TH, THead, TR, TableEmpty } from "@/components/ui/table";
import { CAMPAIGN_STATUS_LABELS, OFFICE_LABELS, type CampaignStatus, type Office } from "@/lib/constants";
import { cn, formatDate, formatNumber } from "@/lib/utils";

export interface CampaignRowData {
  id: string;
  ballotName: string;
  ballotNumber: string | null;
  party: string | null;
  candidateName: string;
  office: string;
  city: string | null;
  state: string | null;
  status: string;
  primaryColor: string;
  createdAt: Date;
  _count: { users: number; voters: number };
}

export function CampaignStatusBadge({ status, className }: { status: string; className?: string }) {
  const label = CAMPAIGN_STATUS_LABELS[status as CampaignStatus] ?? status;
  return (
    <Badge tone={status === "ACTIVE" ? "green" : "red"} className={className}>
      <span className={cn("size-1.5 rounded-full", status === "ACTIVE" ? "bg-emerald-500" : "bg-red-500")} aria-hidden />
      {label}
    </Badge>
  );
}

export function officeLabel(office: string): string {
  return OFFICE_LABELS[office as Office] ?? office;
}

export function placeLabel(city: string | null, state: string | null): string {
  return [city, state].filter(Boolean).join("/") || "—";
}

/** Selo colorido com o número de urna (ou a inicial do nome de urna) */
export function CampaignMark({
  ballotName,
  ballotNumber,
  color,
  className,
}: {
  ballotName: string;
  ballotNumber: string | null;
  color: string;
  className?: string;
}) {
  const text = ballotNumber || ballotName.trim().charAt(0).toUpperCase() || "?";
  return (
    <span
      className={cn(
        "inline-flex size-9 shrink-0 items-center justify-center rounded-lg font-bold text-white tabular-nums shadow-sm",
        text.length > 3 ? "text-[11px]" : "text-sm",
        className,
      )}
      style={{ backgroundColor: color }}
      aria-hidden
    >
      {text}
    </span>
  );
}

function ballotLine(c: Pick<CampaignRowData, "ballotNumber" | "party">): string {
  return [c.ballotNumber, c.party].filter(Boolean).join(" · ");
}

/** Lista de campanhas: cartões no celular e tabela a partir de md */
export function CampaignTable({ campaigns, emptyMessage }: { campaigns: CampaignRowData[]; emptyMessage: React.ReactNode }) {
  return (
    <>
      {/* Celular */}
      <ul className="divide-y divide-slate-100 md:hidden">
        {campaigns.length === 0 && <li className="px-4 py-10 text-center text-sm text-slate-500">{emptyMessage}</li>}
        {campaigns.map((c) => (
          <li key={c.id}>
            <Link href={`/super/campanhas/${c.id}`} className="flex items-start gap-3 px-4 py-3.5 hover:bg-slate-50">
              <CampaignMark ballotName={c.ballotName} ballotNumber={c.ballotNumber} color={c.primaryColor} />
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-2">
                  <p className="truncate font-semibold text-slate-900">{c.ballotName}</p>
                  <CampaignStatusBadge status={c.status} />
                </div>
                <p className="truncate text-xs text-slate-500">
                  {[officeLabel(c.office), ballotLine(c)].filter(Boolean).join(" · ")}
                </p>
                <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
                  <span className="inline-flex items-center gap-1">
                    <MapPin className="size-3.5" aria-hidden /> {placeLabel(c.city, c.state)}
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <Users className="size-3.5" aria-hidden /> {formatNumber(c._count.users)} usuários
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <UsersRound className="size-3.5" aria-hidden /> {formatNumber(c._count.voters)} eleitores
                  </span>
                </div>
              </div>
              <ChevronRight className="mt-2 size-4 shrink-0 text-slate-300" aria-hidden />
            </Link>
          </li>
        ))}
      </ul>

      {/* Tablet/desktop */}
      <div className="hidden md:block">
        <Table>
          <THead>
            <tr>
              <TH>Candidato</TH>
              <TH>Cargo</TH>
              <TH>Cidade/UF</TH>
              <TH>Status</TH>
              <TH className="text-right">Usuários</TH>
              <TH className="text-right">Eleitores</TH>
              <TH>Criada em</TH>
              <TH className="w-10">
                <span className="sr-only">Abrir</span>
              </TH>
            </tr>
          </THead>
          <TBody>
            {campaigns.length === 0 && <TableEmpty colSpan={8}>{emptyMessage}</TableEmpty>}
            {campaigns.map((c) => (
              <TR key={c.id}>
                <TD>
                  <Link href={`/super/campanhas/${c.id}`} className="group flex items-center gap-3">
                    <CampaignMark ballotName={c.ballotName} ballotNumber={c.ballotNumber} color={c.primaryColor} />
                    <span className="min-w-0">
                      <span className="block max-w-56 truncate font-semibold text-slate-900 group-hover:text-brand-700">
                        {c.ballotName}
                      </span>
                      <span className="block max-w-56 truncate text-xs text-slate-500">
                        {ballotLine(c) || c.candidateName}
                      </span>
                    </span>
                  </Link>
                </TD>
                <TD className="whitespace-nowrap">{officeLabel(c.office)}</TD>
                <TD className="whitespace-nowrap">{placeLabel(c.city, c.state)}</TD>
                <TD>
                  <CampaignStatusBadge status={c.status} />
                </TD>
                <TD className="text-right tabular-nums">{formatNumber(c._count.users)}</TD>
                <TD className="text-right tabular-nums">{formatNumber(c._count.voters)}</TD>
                <TD className="whitespace-nowrap">{formatDate(c.createdAt)}</TD>
                <TD>
                  <Link
                    href={`/super/campanhas/${c.id}`}
                    className="inline-flex size-8 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                    aria-label={`Abrir ${c.ballotName}`}
                  >
                    <ChevronRight className="size-4" />
                  </Link>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </div>
    </>
  );
}

/** Link "voltar" discreto acima do título */
export function BackLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="mb-3 inline-flex items-center gap-1.5 text-sm font-medium text-slate-500 hover:text-slate-800">
      <ArrowLeft className="size-4" aria-hidden /> {children}
    </Link>
  );
}

/** Abas por link (?tab=) — renderizadas no servidor */
export function LinkTabs({
  tabs,
  active,
  className,
}: {
  tabs: { value: string; label: React.ReactNode; href: string }[];
  active: string;
  className?: string;
}) {
  return (
    <nav className={cn("flex gap-1 overflow-x-auto border-b border-slate-200 scrollbar-thin", className)} aria-label="Seções">
      {tabs.map((t) => (
        <Link
          key={t.value}
          href={t.href}
          aria-current={t.value === active ? "page" : undefined}
          scroll={false}
          className={cn(
            "-mb-px flex items-center gap-2 border-b-2 px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors",
            t.value === active ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800",
          )}
        >
          {t.label}
        </Link>
      ))}
    </nav>
  );
}
