"use client";

// Mapa territorial: busca os dados agregados conforme os filtros da URL e exibe o mapa
// (bairros / pontos / calor) com painel lateral de indicadores e ranking de bairros.
import * as React from "react";
import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ChevronDown,
  CircleDot,
  Flame,
  Info,
  Layers,
  LocateFixed,
  MapPin,
  MapPinOff,
  RefreshCw,
  Search,
  ShieldCheck,
  Crosshair,
  type LucideIcon,
} from "lucide-react";
import { cn, formatNumber, formatPercent, normalizeText } from "@/lib/utils";
import { parseVoterFilters, voterFiltersToSearchParams } from "@/lib/voter-filters";
import type { GeoQueueCounts, MapData, MapNeighborhood, MapNeighborhoodWithoutGeo } from "@/server/map/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/form";
import { Alert, EmptyState, ProgressBar, Skeleton, Spinner, StatCard } from "@/components/ui/misc";
import { GeocodePendingCard } from "./geocode-pending-card";
import {
  BASEMAPS,
  BASEMAP_KEYS,
  MAP_MODES,
  MAP_MODE_LABELS,
  isBasemap,
  isMapMode,
  type Basemap,
  type MapFocus,
  type MapMode,
} from "./options";
import { binLabel, buildColorScale, HEAT_GRADIENT, shareOf, type ColorBin } from "./scale";

const VoterMap = dynamic(() => import("@/components/map/voter-map"), {
  ssr: false,
  loading: () => <Skeleton className="absolute inset-0 rounded-none" />,
});

const MODE_ICONS: Record<MapMode, LucideIcon> = { bairros: CircleDot, pontos: MapPin, calor: Flame };
const STORAGE_MODE = "efind:mapa:modo";
const STORAGE_BASEMAP = "efind:mapa:base";
const MAP_AREA = "relative isolate h-[60vh] min-h-[60vh] lg:h-[70vh]";

function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}
function writeStorage(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // armazenamento indisponível (modo privado): apenas não lembra a preferência
  }
}

export function MapExplorer({ geoQueue }: { geoQueue: GeoQueueCounts | null }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const qs = searchParams.toString();

  // "Localização no mapa" não se aplica aqui: o mapa mostra quem tem e quem não tem coordenadas
  const filters = React.useMemo(() => {
    const { hasGeo: _ignored, ...rest } = parseVoterFilters(new URLSearchParams(qs));
    return rest;
  }, [qs]);
  const fetchQs = React.useMemo(() => voterFiltersToSearchParams(filters).toString(), [filters]);

  const [data, setData] = React.useState<MapData | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = React.useState(0);

  const [mode, setMode] = React.useState<MapMode>("bairros");
  const [basemap, setBasemap] = React.useState<Basemap>("ruas");
  const [fitNonce, setFitNonce] = React.useState(0);
  const [focus, setFocus] = React.useState<MapFocus | null>(null);
  const [selectedKey, setSelectedKey] = React.useState<string | null>(null);
  const mapAreaRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const m = readStorage(STORAGE_MODE);
    if (isMapMode(m)) setMode(m);
    const b = readStorage(STORAGE_BASEMAP);
    if (isBasemap(b)) setBasemap(b);
  }, []);

  React.useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    fetch(`/api/painel/mapa/dados${fetchQs ? `?${fetchQs}` : ""}`, { signal: controller.signal, cache: "no-store" })
      .then(async (res) => {
        const body: unknown = await res.json().catch(() => null);
        if (res.status === 401) router.refresh(); // sessão expirada → o layout redireciona ao login
        if (!res.ok) {
          const message = body && typeof body === "object" && "error" in body ? String((body as { error: unknown }).error) : null;
          throw new Error(message || "Não foi possível carregar os dados do mapa.");
        }
        return body as MapData;
      })
      .then((next) => {
        setData(next);
        setError(null);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof Error && err.message !== "Failed to fetch" ? err.message : "Falha de conexão. Verifique sua internet.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [fetchQs, reloadNonce, router]);

  const reload = React.useCallback(() => setReloadNonce((n) => n + 1), []);

  const changeMode = (next: MapMode) => {
    setMode(next);
    writeStorage(STORAGE_MODE, next);
  };
  const changeBasemap = (next: Basemap) => {
    setBasemap(next);
    writeStorage(STORAGE_BASEMAP, next);
  };

  const onNavigate = React.useCallback((href: string) => router.push(href), [router]);

  const canViewVoters = data?.canViewVoters ?? false;
  const neighborhoodHref = React.useCallback(
    (n: MapNeighborhood) => {
      if (!canViewVoters || !n.known) return null;
      const sp = voterFiltersToSearchParams({ ...filters, neighborhoods: [n.name], ...(n.city ? { cities: [n.city] } : {}) });
      return `/painel/eleitores?${sp}`;
    },
    [canViewVoters, filters],
  );

  const selectFromRanking = (key: string) => {
    if (mode !== "bairros") changeMode("bairros");
    setSelectedKey(key);
    setFocus({ key, nonce: Date.now() });
    // No celular o painel fica abaixo do mapa: traz o mapa para a tela
    const el = mapAreaRef.current;
    if (el) {
      const rect = el.getBoundingClientRect();
      if (rect.top < 64 || rect.bottom > window.innerHeight) el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  };

  const maxCount = React.useMemo(() => (data ? data.neighborhoods.reduce((m, n) => Math.max(m, n.count), 0) : 0), [data]);
  const bins = React.useMemo(() => buildColorScale(maxCount), [maxCount]);
  const activeKey = data?.neighborhoods.some((n) => n.key === selectedKey) ? selectedKey : null;

  if (!data && loading) return <MapExplorerSkeleton />;

  return (
    <div className="mt-4 space-y-4">
      {error && (
        <Alert tone="danger" title="Não foi possível carregar o mapa">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span>{error}</span>
            <Button size="sm" variant="outline" onClick={reload} loading={loading}>
              <RefreshCw aria-hidden /> Tentar novamente
            </Button>
          </div>
        </Alert>
      )}

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_340px] xl:grid-cols-[minmax(0,1fr)_380px]">
        <Card className="overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 p-3">
            <Segmented
              label="Modo de visualização"
              value={mode}
              onChange={changeMode}
              options={MAP_MODES.map((m) => ({ value: m, label: MAP_MODE_LABELS[m], icon: MODE_ICONS[m] }))}
            />
            <div className="flex items-center gap-2">
              <Segmented
                label="Mapa base"
                value={basemap}
                onChange={changeBasemap}
                options={BASEMAP_KEYS.map((b) => ({ value: b, label: BASEMAPS[b].label, icon: b === "ruas" ? Layers : undefined }))}
              />
              <Button
                variant="outline"
                size="sm"
                onClick={() => setFitNonce((n) => n + 1)}
                disabled={!data?.bounds}
                title="Enquadrar todos os eleitores no mapa"
              >
                <LocateFixed aria-hidden /> Centralizar
              </Button>
            </div>
          </div>

          {data?.truncated && mode !== "bairros" && (
            <p className="flex items-start gap-2 border-b border-amber-100 bg-amber-50 px-4 py-2 text-xs text-amber-900">
              <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              Exibindo uma amostra de {formatNumber(data.points.length)} dos {formatNumber(data.totals.withGeo)} eleitores
              localizados. Use os filtros para detalhar uma região.
            </p>
          )}

          <div ref={mapAreaRef} className={MAP_AREA} role="region" aria-label="Mapa dos eleitores">
            {data ? (
              <VoterMap
                data={data}
                mode={mode}
                basemap={basemap}
                fitNonce={fitNonce}
                focus={focus}
                selectedKey={activeKey}
                neighborhoodHref={neighborhoodHref}
                onNavigate={onNavigate}
                onSelectNeighborhood={setSelectedKey}
              />
            ) : (
              <MapUnavailable onRetry={reload} />
            )}

            {data && data.totals.withGeo > 0 && <MapLegend mode={mode} bins={bins} />}

            {loading && data && (
              <div className="absolute top-3 right-3 z-[1000] inline-flex items-center gap-2 rounded-full bg-white/95 px-3 py-1.5 text-xs font-medium text-slate-600 shadow-md">
                <Spinner className="size-3.5" /> Atualizando...
              </div>
            )}

            {data && data.totals.withGeo === 0 && (
              <div className="absolute inset-0 z-[1000] flex items-center justify-center bg-slate-50/70 p-4 backdrop-blur-[1px]">
                <div className="max-w-sm rounded-xl border border-slate-200 bg-white shadow-sm">
                  <EmptyState
                    icon={MapPinOff}
                    title="Nenhum eleitor com localização para os filtros selecionados"
                    description={
                      data.totals.voters > 0
                        ? `${formatNumber(data.totals.voters)} eleitor(es) encontrado(s) ainda sem localização (CEP ausente ou aguardando processamento).`
                        : "Ajuste os filtros ou cadastre eleitores com CEP para vê-los no mapa."
                    }
                  />
                </div>
              </div>
            )}
          </div>

          <p className="flex items-start gap-2 border-t border-slate-100 px-4 py-3 text-xs text-slate-500">
            <ShieldCheck className="mt-0.5 size-3.5 shrink-0 text-slate-400" aria-hidden />
            As coordenadas são aproximadas (nível de CEP/logradouro), e não do endereço exato, para proteger a privacidade dos
            eleitores.
          </p>
        </Card>

        <aside className="space-y-4" aria-label="Resumo do mapa">
          {data && (
            <>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 lg:grid-cols-1">
                <StatCard
                  className="p-4"
                  label="No mapa"
                  value={formatNumber(data.totals.withGeo)}
                  hint={`${formatPercent(shareOf(data.totals.withGeo, data.totals.voters))} de ${formatNumber(data.totals.voters)} eleitores`}
                  icon={MapPin}
                  tone="brand"
                />
                <StatCard
                  className="p-4"
                  label="Sem localização"
                  value={formatNumber(data.totals.withoutGeo)}
                  hint="Sem CEP ou ainda não localizados"
                  icon={MapPinOff}
                  tone="yellow"
                />
                <StatCard
                  className="p-4"
                  label="Aproximados"
                  value={formatNumber(data.totals.approximate)}
                  hint="Localizados pelo bairro ou cidade"
                  icon={Crosshair}
                  tone="blue"
                />
              </div>

              <NeighborhoodRanking
                neighborhoods={data.neighborhoods}
                total={data.totals.voters}
                maxCount={maxCount}
                selectedKey={activeKey}
                onSelect={selectFromRanking}
              />

              {data.neighborhoodsWithoutGeo.length > 0 && (
                <WithoutGeoList items={data.neighborhoodsWithoutGeo} total={data.totals.voters} />
              )}
            </>
          )}
          {geoQueue && <GeocodePendingCard queue={geoQueue} onDone={reload} />}
        </aside>
      </div>
    </div>
  );
}

/** Controle segmentado (rádio acessível) */
function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string; icon?: LucideIcon }[];
  onChange: (value: T) => void;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg bg-slate-100 p-1">
      {options.map((o) => {
        const Icon = o.icon;
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(o.value)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium whitespace-nowrap transition-colors",
              "focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:outline-none",
              active ? "bg-white text-brand-700 shadow-sm" : "text-slate-600 hover:text-slate-900",
            )}
          >
            {Icon && <Icon className="size-4" aria-hidden />}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

function MapLegend({ mode, bins }: { mode: MapMode; bins: ColorBin[] }) {
  const [open, setOpen] = React.useState(true);
  const title = mode === "bairros" ? "Eleitores por bairro" : mode === "pontos" ? "Eleitores" : "Concentração";
  const gradient = Object.entries(HEAT_GRADIENT)
    .sort(([a], [b]) => Number(a) - Number(b))
    .map(([stop, color]) => `${color} ${Number(stop) * 100}%`)
    .join(", ");

  return (
    <div className="absolute bottom-7 left-3 z-[1000] max-w-[calc(100%-1.5rem)] rounded-lg border border-slate-200 bg-white/95 text-xs shadow-md backdrop-blur">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-3 py-2 font-semibold text-slate-700"
      >
        {title}
        <ChevronDown className={cn("size-3.5 text-slate-400 transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      {open && (
        <div className="border-t border-slate-100 px-3 pt-2 pb-3">
          {mode === "bairros" && (
            <>
              <ul className="space-y-1">
                {bins.map((b) => (
                  <li key={`${b.min}-${b.max}`} className="flex items-center gap-2">
                    <span className="size-3 shrink-0 rounded-full ring-1 ring-slate-300" style={{ backgroundColor: b.color }} aria-hidden />
                    <span className="text-slate-600 tabular-nums">{binLabel(b)}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-2 max-w-40 text-[11px] text-slate-500">Tamanho do círculo proporcional ao total.</p>
            </>
          )}
          {mode === "pontos" && (
            <ul className="space-y-1.5">
              <li className="flex items-center gap-2">
                <span className="size-3 shrink-0 rounded-full border-2 border-white bg-brand-600 ring-1 ring-brand-300" aria-hidden />
                <span className="text-slate-600">Eleitor</span>
              </li>
              <li className="flex items-center gap-2">
                <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-brand-600 text-[9px] font-bold text-white" aria-hidden>
                  9
                </span>
                <span className="text-slate-600">Grupo próximo (toque para ampliar)</span>
              </li>
            </ul>
          )}
          {mode === "calor" && (
            <>
              <div className="h-2 w-36 rounded-full" style={{ background: `linear-gradient(to right, ${gradient})` }} aria-hidden />
              <div className="mt-1 flex w-36 justify-between text-[11px] text-slate-500">
                <span>Menor</span>
                <span>Maior</span>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function MapUnavailable({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="absolute inset-0 flex items-center justify-center bg-slate-50">
      <EmptyState
        icon={MapPinOff}
        title="Mapa indisponível"
        description="Não conseguimos carregar os dados agora."
        action={
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RefreshCw aria-hidden /> Tentar novamente
          </Button>
        }
      />
    </div>
  );
}

function NeighborhoodRanking({
  neighborhoods,
  total,
  maxCount,
  selectedKey,
  onSelect,
}: {
  neighborhoods: MapNeighborhood[];
  total: number;
  maxCount: number;
  selectedKey: string | null;
  onSelect: (key: string) => void;
}) {
  const [query, setQuery] = React.useState("");
  const ranked = React.useMemo(() => neighborhoods.map((n, i) => ({ n, rank: i + 1 })), [neighborhoods]);
  const filtered = React.useMemo(() => {
    const q = normalizeText(query);
    if (!q) return ranked;
    return ranked.filter(({ n }) => normalizeText(`${n.name} ${n.city ?? ""}`).includes(q));
  }, [ranked, query]);

  return (
    <Card>
      <CardHeader className="gap-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle>Ranking de bairros</CardTitle>
          <Badge tone="brand">{formatNumber(neighborhoods.length)}</Badge>
        </div>
        {neighborhoods.length > 0 && (
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-slate-400" aria-hidden />
            <Input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Buscar bairro..."
              aria-label="Buscar bairro no ranking"
              className="pl-9"
            />
          </div>
        )}
      </CardHeader>
      {neighborhoods.length === 0 ? (
        <CardContent>
          <p className="py-4 text-center text-sm text-slate-500">Nenhum bairro com eleitores localizados.</p>
        </CardContent>
      ) : filtered.length === 0 ? (
        <CardContent>
          <p className="py-4 text-center text-sm text-slate-500">Nenhum bairro encontrado para “{query}”.</p>
        </CardContent>
      ) : (
        <ul className="max-h-[440px] divide-y divide-slate-100 overflow-y-auto scrollbar-thin">
          {filtered.map(({ n, rank }) => {
            const selected = n.key === selectedKey;
            return (
              <li key={n.key}>
                <button
                  type="button"
                  onClick={() => onSelect(n.key)}
                  aria-current={selected || undefined}
                  title="Ver no mapa"
                  className={cn(
                    "w-full px-5 py-3 text-left transition-colors hover:bg-slate-50 focus-visible:bg-slate-50 focus-visible:outline-none",
                    selected && "bg-brand-50/70 hover:bg-brand-50",
                  )}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className={cn("truncate text-sm font-medium", n.known ? "text-slate-900" : "text-slate-500 italic")}>
                        <span className="mr-1.5 text-xs text-slate-400 not-italic tabular-nums">{rank}.</span>
                        {n.name}
                      </p>
                      {n.city && <p className="truncate text-xs text-slate-500">{n.city}</p>}
                    </div>
                    <div className="shrink-0 text-right">
                      <p className="text-sm font-semibold text-slate-900 tabular-nums">{formatNumber(n.count)}</p>
                      <p className="text-xs text-slate-500 tabular-nums">{formatPercent(shareOf(n.count, total))}</p>
                    </div>
                  </div>
                  <ProgressBar value={n.count} max={maxCount} className="mt-2 h-1.5" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

const WITHOUT_GEO_PREVIEW = 8;

function WithoutGeoList({ items, total }: { items: MapNeighborhoodWithoutGeo[]; total: number }) {
  const [expanded, setExpanded] = React.useState(false);
  const visible = expanded ? items : items.slice(0, WITHOUT_GEO_PREVIEW);
  const sum = items.reduce((s, i) => s + i.count, 0);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Bairros sem localização</CardTitle>
        <CardDescription>
          {formatNumber(sum)} eleitor(es) em bairros que ainda não têm coordenadas e por isso não aparecem no mapa
          {total > 0 ? ` (${formatPercent(shareOf(sum, total))} do total)` : ""}.
        </CardDescription>
      </CardHeader>
      <ul className={cn("divide-y divide-slate-100", expanded && "max-h-[360px] overflow-y-auto scrollbar-thin")}>
        {visible.map((i) => (
          <li key={i.key} className="flex items-center justify-between gap-3 px-5 py-2.5">
            <div className="min-w-0">
              <p className={cn("truncate text-sm", i.known ? "text-slate-800" : "text-slate-500 italic")}>{i.name}</p>
              {i.city && <p className="truncate text-xs text-slate-500">{i.city}</p>}
            </div>
            <span className="shrink-0 text-sm font-semibold text-slate-900 tabular-nums">{formatNumber(i.count)}</span>
          </li>
        ))}
      </ul>
      {items.length > WITHOUT_GEO_PREVIEW && (
        <div className="border-t border-slate-100 px-5 py-2.5">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-sm font-medium text-brand-600 hover:text-brand-700"
            aria-expanded={expanded}
          >
            {expanded ? "Mostrar menos" : `Mostrar todos (${formatNumber(items.length)})`}
          </button>
        </div>
      )}
    </Card>
  );
}

/** Esqueleto exibido enquanto os dados do mapa carregam */
export function MapExplorerSkeleton() {
  return (
    <div className="mt-4 grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_340px] xl:grid-cols-[minmax(0,1fr)_380px]" aria-busy="true">
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 p-3">
          <Skeleton className="h-9 w-64" />
          <Skeleton className="h-9 w-44" />
        </div>
        <div className={MAP_AREA}>
          <Skeleton className="absolute inset-0 rounded-none" />
          <div className="absolute inset-0 flex items-center justify-center">
            <Spinner className="size-6" />
          </div>
        </div>
        <div className="border-t border-slate-100 px-4 py-3">
          <Skeleton className="h-3 w-3/4" />
        </div>
      </Card>
      <div className="space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 lg:grid-cols-1">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
        <Skeleton className="h-80 rounded-xl" />
      </div>
    </div>
  );
}
