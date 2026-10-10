import type { Metadata } from "next";
import { Plus, Search, ShieldCheck } from "lucide-react";
import { requireSuperAdmin } from "@/lib/auth";
import { Button, ButtonLink } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/form";
import { Alert, EmptyState, PageHeader } from "@/components/ui/misc";
import { Pagination } from "@/components/ui/pagination";
import { CampaignTable } from "@/components/super/campaign-display";
import { CAMPAIGN_STATUSES, CAMPAIGN_STATUS_LABELS } from "@/lib/constants";
import { parseCampaignListParams } from "@/server/super/filters";
import { listCampaigns } from "@/server/super/queries";

export const metadata: Metadata = { title: "Campanhas" };

const PAGE_SIZE = 25;

export default async function CampaignsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  await requireSuperAdmin();
  const sp = await searchParams;
  const params = parseCampaignListParams(sp);
  const { items, total } = await listCampaigns(params, PAGE_SIZE);
  const hasFilters = !!(params.q || params.status);
  const deleted = sp.excluida === "1";

  const newButton = (
    <ButtonLink href="/super/campanhas/nova">
      <Plus aria-hidden /> Nova campanha
    </ButtonLink>
  );

  return (
    <>
      <PageHeader
        title="Candidatos / campanhas"
        description="Cada campanha é um ambiente isolado: nenhum candidato enxerga a campanha do outro."
        actions={newButton}
      />

      {deleted && (
        <Alert tone="success" title="Campanha excluída definitivamente." className="mb-4">
          Todos os dados da campanha foram removidos. O registro da exclusão está na auditoria.
        </Alert>
      )}

      {total === 0 && !hasFilters ? (
        <Card>
          <EmptyState
            icon={ShieldCheck}
            title="Nenhuma campanha cadastrada"
            description="Cadastre o candidato e o primeiro administrador para começar."
            action={newButton}
          />
        </Card>
      ) : (
        <Card>
          <form method="get" className="flex flex-col gap-3 border-b border-slate-100 p-4 sm:flex-row sm:items-end" role="search">
            <Field label="Buscar" htmlFor="q" className="flex-1">
              <div className="relative">
                <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-slate-400" aria-hidden />
                <Input
                  id="q"
                  name="q"
                  type="search"
                  defaultValue={params.q}
                  maxLength={100}
                  placeholder="Candidato, nome de urna, partido ou cidade"
                  className="pl-9"
                />
              </div>
            </Field>
            <Field label="Status" htmlFor="status" className="sm:w-44">
              <Select id="status" name="status" defaultValue={params.status}>
                <option value="">Todos</option>
                {CAMPAIGN_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {CAMPAIGN_STATUS_LABELS[s]}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="flex gap-2">
              <Button type="submit" variant="secondary" className="flex-1 sm:flex-none">
                Filtrar
              </Button>
              {hasFilters && (
                <ButtonLink href="/super/campanhas" variant="ghost" className="flex-1 sm:flex-none">
                  Limpar
                </ButtonLink>
              )}
            </div>
          </form>

          <CampaignTable
            campaigns={items}
            emptyMessage={hasFilters ? "Nenhuma campanha encontrada com esses filtros." : "Nenhuma campanha nesta página."}
          />

          {total > 0 && (
            <div className="border-t border-slate-100 px-4">
              <Pagination
                page={params.page}
                pageSize={PAGE_SIZE}
                total={total}
                basePath="/super/campanhas"
                searchParams={{ q: params.q || undefined, status: params.status || undefined }}
              />
            </div>
          )}
        </Card>
      )}
    </>
  );
}
