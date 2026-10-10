import type { Metadata } from "next";
import Link from "next/link";
import Form from "next/form";
import { Download, FilterX, History, Search, ShieldCheck } from "lucide-react";
import { requirePermission } from "@/lib/auth";
import { formatDateTime, formatNumber } from "@/lib/utils";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Pagination,
  parsePage,
  Select,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@/components/ui";
import { buttonClasses } from "@/components/ui/button";
import { AUDIT_PAGE_SIZE, auditFiltersToSearchParams, hasAuditFilters } from "@/server/settings/audit-filters";
import { getAuditContext, listAuditLogs, parseFiltersFor, type AuditRow } from "@/server/settings/audit-log";

export const metadata: Metadata = { title: "Auditoria" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function UserCell({ row }: { row: AuditRow }) {
  if (!row.userName) return <span className="text-slate-400 italic">Sistema</span>;
  return (
    <div className="min-w-0">
      <p className="truncate font-medium text-slate-800">{row.userName}</p>
      {row.byPlatform ? (
        <Badge tone="purple" className="mt-0.5">
          Suporte E-Find
        </Badge>
      ) : (
        row.userRoleLabel && <p className="text-xs text-slate-500">{row.userRoleLabel}</p>
      )}
    </div>
  );
}

function EntityCell({ row }: { row: AuditRow }) {
  if (!row.entity) return <span className="text-slate-400">—</span>;
  return (
    <div className="min-w-0">
      <p className="text-slate-700">{row.entity}</p>
      {row.entityId && (
        <p className="max-w-36 truncate font-mono text-[11px] text-slate-400" title={row.entityId}>
          {row.entityId}
        </p>
      )}
    </div>
  );
}

function DetailsCell({ details }: { details: string | null }) {
  if (!details) return <span className="text-slate-400">—</span>;
  return (
    <details className="group">
      <summary className="cursor-pointer list-none text-xs font-medium text-brand-600 select-none hover:text-brand-700 [&::-webkit-details-marker]:hidden">
        <span className="group-open:hidden">Ver detalhes</span>
        <span className="hidden group-open:inline">Ocultar detalhes</span>
      </summary>
      <pre className="mt-2 max-h-64 max-w-full overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-[11px] leading-relaxed text-slate-100 scrollbar-thin sm:max-w-md">
        {details}
      </pre>
    </details>
  );
}

export default async function AuditoriaPage({ searchParams }: { searchParams: SearchParams }) {
  const user = await requirePermission("auditoria");
  const sp = await searchParams;
  const context = await getAuditContext(user);
  const filters = parseFiltersFor(context, sp);
  const { rows, total, page } = await listAuditLogs(user, context, filters, parsePage(sp.page));
  const filterParams = auditFiltersToSearchParams(filters);
  const filtered = hasAuditFilters(filters);
  const query = filterParams.toString();
  const exportHref = `/painel/auditoria/export${query ? `?${query}` : ""}`;

  return (
    <>
      <PageHeader
        title="Auditoria"
        description="Registro de acessos, alterações, exportações e disparos realizados na campanha."
        actions={
          total > 0 ? (
            <a href={exportHref} download className={buttonClasses({ variant: "outline" })}>
              <Download aria-hidden /> Exportar CSV
            </a>
          ) : undefined
        }
      />

      <Alert tone="info" className="mb-6">
        <span className="flex gap-2">
          <ShieldCheck className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>
            A LGPD (art. 37) exige que quem trata dados pessoais mantenha registro das operações realizadas. Esta trilha mostra
            quem fez o quê e quando — logins, cadastros, alterações, exportações e disparos — e ajuda a campanha a prestar
            contas a eleitores e autoridades.
            {context.options.scoped && " Você vê apenas as ações registradas pela sua rede."}
          </span>
        </span>
      </Alert>

      <Card className="mb-6">
        <Form action="/painel/auditoria" className="grid gap-4 p-4 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_auto_auto_auto] lg:items-end">
          <Field label="Usuário" htmlFor="f-user">
            <Select id="f-user" name="user" defaultValue={filters.userId ?? ""}>
              <option value="">Todos</option>
              {context.options.users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name} · {u.roleLabel}
                  {u.active ? "" : " (inativo)"}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Ação" htmlFor="f-action">
            <Select id="f-action" name="action" defaultValue={filters.action ?? ""}>
              <option value="">Todas</option>
              {context.options.actionGroups.map((g) => (
                <optgroup key={g.label} label={g.label}>
                  {g.options.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </optgroup>
              ))}
            </Select>
          </Field>
          <Field label="De" htmlFor="f-from">
            <Input id="f-from" name="from" type="date" defaultValue={filters.from ?? ""} className="lg:w-40" />
          </Field>
          <Field label="Até" htmlFor="f-to">
            <Input id="f-to" name="to" type="date" defaultValue={filters.to ?? ""} className="lg:w-40" />
          </Field>
          <div className="flex gap-2 sm:col-span-2 lg:col-span-1">
            <Button type="submit" className="flex-1 lg:flex-none">
              <Search aria-hidden /> Filtrar
            </Button>
            {filtered && (
              <Link href="/painel/auditoria" className={buttonClasses({ variant: "ghost" })}>
                <FilterX aria-hidden /> Limpar
              </Link>
            )}
          </div>
        </Form>
      </Card>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-5 py-3">
          <p className="text-sm text-slate-600">
            <span className="font-semibold text-slate-900">{formatNumber(total)}</span>{" "}
            {total === 1 ? "registro" : "registros"}
            {filtered ? " com os filtros aplicados" : ""}
          </p>
          <p className="text-xs text-slate-400">Horários de Brasília</p>
        </div>

        {rows.length === 0 ? (
          <EmptyState
            icon={History}
            title={filtered ? "Nenhum registro encontrado" : "Nenhum registro ainda"}
            description={
              filtered
                ? "Não há ações registradas para os filtros escolhidos. Ajuste o período ou limpe os filtros."
                : "As ações da equipe (logins, cadastros, alterações, exportações e disparos) aparecerão aqui."
            }
            action={
              filtered ? (
                <Link href="/painel/auditoria" className={buttonClasses({ variant: "outline" })}>
                  <FilterX aria-hidden /> Limpar filtros
                </Link>
              ) : undefined
            }
          />
        ) : (
          <>
            {/* Celular: lista */}
            <ul className="divide-y divide-slate-100 md:hidden">
              {rows.map((row) => (
                <li key={row.id} className="space-y-2 px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <p className="font-medium text-slate-900">{row.actionLabel}</p>
                    <time className="shrink-0 text-xs text-slate-500 tabular-nums" dateTime={row.createdAt.toISOString()}>
                      {formatDateTime(row.createdAt)}
                    </time>
                  </div>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                    <UserCell row={row} />
                  </div>
                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                    {row.entity && <span>Entidade: {row.entity}</span>}
                    {row.ip && <span className="font-mono">IP {row.ip}</span>}
                  </div>
                  <DetailsCell details={row.details} />
                </li>
              ))}
            </ul>

            {/* Telas maiores: tabela */}
            <div className="hidden md:block">
              <Table>
                <THead>
                  <TR className="hover:bg-transparent">
                    <TH>Data/hora</TH>
                    <TH>Usuário</TH>
                    <TH>Ação</TH>
                    <TH>Entidade</TH>
                    <TH>IP</TH>
                    <TH>Detalhes</TH>
                  </TR>
                </THead>
                <TBody>
                  {rows.map((row) => (
                    <TR key={row.id} className="align-top">
                      <TD className="whitespace-nowrap tabular-nums">
                        <time dateTime={row.createdAt.toISOString()}>{formatDateTime(row.createdAt)}</time>
                      </TD>
                      <TD className="max-w-48">
                        <UserCell row={row} />
                      </TD>
                      <TD>
                        <p className="font-medium text-slate-800">{row.actionLabel}</p>
                        <p className="font-mono text-[11px] text-slate-400">{row.action}</p>
                      </TD>
                      <TD>
                        <EntityCell row={row} />
                      </TD>
                      <TD className="font-mono text-xs whitespace-nowrap">{row.ip ?? "—"}</TD>
                      <TD>
                        <DetailsCell details={row.details} />
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </div>

            <div className="border-t border-slate-100 px-4">
              <Pagination
                page={page}
                pageSize={AUDIT_PAGE_SIZE}
                total={total}
                basePath="/painel/auditoria"
                searchParams={filterParams}
              />
            </div>
          </>
        )}
      </Card>
    </>
  );
}
