"use client";

// Mapa Leaflet do módulo Mapa territorial. Só roda no navegador: é carregado com
// dynamic(() => import("@/components/map/voter-map"), { ssr: false }) em map-explorer.tsx.
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import "leaflet.markercluster/dist/MarkerCluster.Default.css";
import "./voter-map.css";

import * as React from "react";
import Link from "next/link";
import * as L from "leaflet";
import "leaflet.markercluster";
import "leaflet.heat";
import type { HeatLatLng, HeatLayerFactory } from "leaflet.heat";
import { CircleMarker, MapContainer, Popup, TileLayer, Tooltip, useMap } from "react-leaflet";
import { ArrowRight } from "lucide-react";
import { formatNumber } from "@/lib/utils";
import type { MapBounds, MapData, MapNeighborhood, MapPoint } from "@/server/map/types";
import {
  BASEMAPS,
  BRAZIL_CENTER,
  BRAZIL_ZOOM,
  FIT_MAX_ZOOM,
  FOCUS_ZOOM,
  type Basemap,
  type MapFocus,
  type MapMode,
} from "./options";
import { buildColorScale, colorForCount, HEAT_GRADIENT, radiusForCount, type ColorBin } from "./scale";

type LeafletWithPlugins = typeof L & { heatLayer: HeatLayerFactory };

/** Os plugins (markercluster, heat) se registram no objeto global window.L criado pelo Leaflet */
function leaflet(): LeafletWithPlugins {
  const fromWindow = typeof window !== "undefined" ? (window as unknown as { L?: LeafletWithPlugins }).L : undefined;
  return fromWindow ?? (L as unknown as LeafletWithPlugins);
}

export interface VoterMapProps {
  data: MapData;
  mode: MapMode;
  basemap: Basemap;
  /** Incrementado pelo botão "Centralizar" */
  fitNonce: number;
  focus: MapFocus | null;
  selectedKey: string | null;
  /** Link "Ver eleitores" do bairro (null = sem permissão ou bairro não informado) */
  neighborhoodHref: (n: MapNeighborhood) => string | null;
  /** Navegação interna (Next) a partir de popups criados fora do React */
  onNavigate: (href: string) => void;
  onSelectNeighborhood: (key: string) => void;
}

export default function VoterMap({
  data,
  mode,
  basemap,
  fitNonce,
  focus,
  selectedKey,
  neighborhoodHref,
  onNavigate,
  onSelectNeighborhood,
}: VoterMapProps) {
  const base = BASEMAPS[basemap];
  const markers = React.useRef(new Map<string, L.CircleMarker>());
  const maxCount = React.useMemo(() => data.neighborhoods.reduce((m, n) => Math.max(m, n.count), 0), [data.neighborhoods]);
  const bins = React.useMemo(() => buildColorScale(maxCount), [maxCount]);

  return (
    <MapContainer
      center={BRAZIL_CENTER}
      zoom={BRAZIL_ZOOM}
      minZoom={3}
      maxZoom={19}
      scrollWheelZoom
      className="efind-map"
      style={{ height: "100%", width: "100%" }}
    >
      <TileLayer key={basemap} url={base.url} attribution={base.attribution} subdomains={base.subdomains} maxZoom={base.maxZoom} />
      <AutoResize />
      <FitBounds bounds={data.bounds} nonce={fitNonce} />
      {mode === "bairros" && (
        <NeighborhoodLayer
          neighborhoods={data.neighborhoods}
          bins={bins}
          maxCount={maxCount}
          selectedKey={selectedKey}
          markers={markers}
          neighborhoodHref={neighborhoodHref}
          onSelect={onSelectNeighborhood}
        />
      )}
      {mode === "pontos" && <ClusterLayer points={data.points} canViewVoters={data.canViewVoters} onNavigate={onNavigate} />}
      {mode === "calor" && <HeatLayer points={data.points} />}
      <FocusNeighborhood focus={focus} neighborhoods={data.neighborhoods} markers={markers} />
    </MapContainer>
  );
}

/** Recalcula o tamanho do mapa quando o contêiner muda (rotação do celular, painel lateral) */
function AutoResize() {
  const map = useMap();
  React.useEffect(() => {
    const el = map.getContainer();
    const observer = new ResizeObserver(() => map.invalidateSize());
    observer.observe(el);
    return () => observer.disconnect();
  }, [map]);
  return null;
}

/** Enquadra os eleitores sempre que os dados mudam ou o usuário pede "Centralizar" */
function FitBounds({ bounds, nonce }: { bounds: MapBounds | null; nonce: number }) {
  const map = useMap();
  React.useEffect(() => {
    if (bounds) map.fitBounds(bounds, { padding: [32, 32], maxZoom: FIT_MAX_ZOOM });
    else map.setView(BRAZIL_CENTER, BRAZIL_ZOOM);
  }, [map, bounds, nonce]);
  return null;
}

function NeighborhoodLayer({
  neighborhoods,
  bins,
  maxCount,
  selectedKey,
  markers,
  neighborhoodHref,
  onSelect,
}: {
  neighborhoods: MapNeighborhood[];
  bins: ColorBin[];
  maxCount: number;
  selectedKey: string | null;
  markers: React.RefObject<Map<string, L.CircleMarker>>;
  neighborhoodHref: (n: MapNeighborhood) => string | null;
  onSelect: (key: string) => void;
}) {
  // Ordenados do maior para o menor: os círculos pequenos ficam por cima e continuam clicáveis
  return (
    <>
      {neighborhoods.map((n) => {
        const radius = radiusForCount(n.count, maxCount);
        const selected = n.key === selectedKey;
        return (
          <CircleMarker
            key={n.key}
            ref={(instance) => {
              if (instance) markers.current.set(n.key, instance);
              else markers.current.delete(n.key);
            }}
            center={[n.lat, n.lng]}
            radius={radius}
            pathOptions={{
              color: selected ? "#0f172a" : "#ffffff",
              weight: selected ? 3 : 1.5,
              fillColor: colorForCount(n.count, bins),
              fillOpacity: 0.82,
            }}
            eventHandlers={{ click: () => onSelect(n.key) }}
          >
            <Tooltip direction="top" offset={[0, -radius]} opacity={1}>
              {n.name} · {formatNumber(n.count)}
            </Tooltip>
            <NeighborhoodPopup n={n} href={neighborhoodHref(n)} />
          </CircleMarker>
        );
      })}
    </>
  );
}

function NeighborhoodPopup({ n, href }: { n: MapNeighborhood; href: string | null }) {
  const unmapped = n.count - n.mapped;
  return (
    <Popup minWidth={220} maxWidth={300} autoPanPadding={[16, 16]}>
      <div className="space-y-3">
        <div>
          <p className="text-sm font-semibold text-slate-900">{n.name}</p>
          <p className="text-xs text-slate-500">{n.city ?? "Cidade não informada"}</p>
        </div>
        <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-xs">
          <dt className="text-slate-500">Total de eleitores</dt>
          <dd className="text-right font-semibold text-slate-900 tabular-nums">{formatNumber(n.count)}</dd>
          <dt className="text-slate-500">Aptos a WhatsApp</dt>
          <dd className="text-right font-semibold text-slate-900 tabular-nums">{formatNumber(n.messageable)}</dd>
          <dt className="text-slate-500">Apoiadores</dt>
          <dd className="text-right font-semibold text-slate-900 tabular-nums">{formatNumber(n.supporters)}</dd>
          {unmapped > 0 && (
            <>
              <dt className="text-slate-500">Sem localização no mapa</dt>
              <dd className="text-right font-semibold text-slate-900 tabular-nums">{formatNumber(unmapped)}</dd>
            </>
          )}
        </dl>
        {n.topMembers.length > 0 && (
          <div>
            <p className="text-[11px] font-semibold tracking-wide text-slate-500 uppercase">Quem mais cadastrou</p>
            <ol className="mt-1 space-y-0.5 text-xs">
              {n.topMembers.map((m, i) => (
                <li key={`${i}-${m.name}`} className="flex items-center justify-between gap-3">
                  <span className="truncate text-slate-700">
                    {i + 1}. {m.name}
                  </span>
                  <span className="font-medium text-slate-900 tabular-nums">{formatNumber(m.count)}</span>
                </li>
              ))}
            </ol>
          </div>
        )}
        {href && (
          <Link href={href} className="efind-map-link inline-flex items-center gap-1 text-xs">
            Ver eleitores <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        )}
      </div>
    </Popup>
  );
}

/** Popup de um ponto individual (montado fora do React pelo markercluster) — sem dados pessoais */
function pointPopup(id: string, canViewVoters: boolean, navigate: (href: string) => void): HTMLElement {
  const root = document.createElement("div");
  root.className = "space-y-1";
  const title = document.createElement("p");
  title.className = "text-sm font-semibold text-slate-900";
  title.textContent = "Eleitor cadastrado";
  const note = document.createElement("p");
  note.className = "text-xs text-slate-500";
  note.textContent = "Localização aproximada (CEP/logradouro).";
  root.append(title, note);
  if (canViewVoters) {
    const href = `/painel/eleitores/${encodeURIComponent(id)}`;
    const link = document.createElement("a");
    link.href = href;
    link.className = "efind-map-link inline-block pt-1 text-xs";
    link.textContent = "Ver cadastro →";
    link.addEventListener("click", (e) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      e.preventDefault();
      navigate(href);
    });
    root.append(link);
  }
  return root;
}

function clusterLabel(n: number): string {
  if (n >= 10000) return `${Math.round(n / 1000)} mil`;
  return n.toLocaleString("pt-BR");
}

function ClusterLayer({
  points,
  canViewVoters,
  onNavigate,
}: {
  points: MapPoint[];
  canViewVoters: boolean;
  onNavigate: (href: string) => void;
}) {
  const map = useMap();
  const navigateRef = React.useRef(onNavigate);
  React.useEffect(() => {
    navigateRef.current = onNavigate;
  }, [onNavigate]);

  React.useEffect(() => {
    const Lx = leaflet();
    const icon = Lx.divIcon({ className: "efind-point", html: "", iconSize: [14, 14], iconAnchor: [7, 7], popupAnchor: [0, -8] });
    const group = Lx.markerClusterGroup({
      chunkedLoading: true,
      showCoverageOnHover: false,
      spiderfyOnMaxZoom: true,
      maxClusterRadius: 56,
      iconCreateFunction: (cluster) => {
        const count = cluster.getChildCount();
        const size = count < 10 ? "sm" : count < 100 ? "md" : "lg";
        const px = size === "sm" ? 34 : size === "md" ? 42 : 52;
        return Lx.divIcon({
          html: `<span>${clusterLabel(count)}</span>`,
          className: `efind-cluster efind-cluster-${size}`,
          iconSize: Lx.point(px, px),
        });
      },
    });
    const layers = points.map((p) =>
      Lx.marker([p.lat, p.lng], { icon, keyboard: false }).bindPopup(
        () => pointPopup(p.id, canViewVoters, (href) => navigateRef.current(href)),
        { minWidth: 180 },
      ),
    );
    group.addLayers(layers);
    map.addLayer(group);
    return () => {
      map.removeLayer(group);
    };
  }, [map, points, canViewVoters]);
  return null;
}

function HeatLayer({ points }: { points: MapPoint[] }) {
  const map = useMap();
  React.useEffect(() => {
    if (!points.length) return;
    const latlngs: HeatLatLng[] = points.map((p) => [p.lat, p.lng, 1]);
    const layer = leaflet().heatLayer(latlngs, { radius: 22, blur: 18, maxZoom: 16, minOpacity: 0.35, gradient: HEAT_GRADIENT });
    layer.addTo(map);
    return () => {
      map.removeLayer(layer);
    };
  }, [map, points]);
  return null;
}

/** Voa até o bairro escolhido no ranking e abre o popup dele */
function FocusNeighborhood({
  focus,
  neighborhoods,
  markers,
}: {
  focus: MapFocus | null;
  neighborhoods: MapNeighborhood[];
  markers: React.RefObject<Map<string, L.CircleMarker>>;
}) {
  const map = useMap();
  const listRef = React.useRef(neighborhoods);
  React.useEffect(() => {
    listRef.current = neighborhoods;
  }, [neighborhoods]);

  React.useEffect(() => {
    if (!focus) return;
    const target = listRef.current.find((n) => n.key === focus.key);
    if (!target) return;
    let done = false;
    const open = () => {
      if (done) return;
      done = true;
      markers.current.get(target.key)?.openPopup();
    };
    const timer = window.setTimeout(open, 1600);
    map.once("moveend", open);
    map.flyTo([target.lat, target.lng], Math.max(map.getZoom(), FOCUS_ZOOM), { duration: 0.8 });
    return () => {
      done = true;
      window.clearTimeout(timer);
      map.off("moveend", open);
    };
  }, [map, focus, markers]);
  return null;
}
