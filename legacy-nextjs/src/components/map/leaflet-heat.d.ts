// Declaração mínima do plugin leaflet.heat (o pacote não traz tipos). O plugin registra
// L.heatLayer no objeto global do Leaflet ao ser importado (import "leaflet.heat").
declare module "leaflet.heat" {
  import type { Layer, LatLngExpression } from "leaflet";

  /** [latitude, longitude, intensidade?] */
  export type HeatLatLng = [number, number] | [number, number, number];

  export interface HeatLayerOptions {
    minOpacity?: number;
    maxZoom?: number;
    max?: number;
    radius?: number;
    blur?: number;
    gradient?: Record<number, string>;
  }

  export interface HeatLayer extends Layer {
    setLatLngs(latlngs: Array<HeatLatLng | LatLngExpression>): this;
    addLatLng(latlng: HeatLatLng | LatLngExpression): this;
    setOptions(options: HeatLayerOptions): this;
    redraw(): this;
  }

  export type HeatLayerFactory = (latlngs: Array<HeatLatLng | LatLngExpression>, options?: HeatLayerOptions) => HeatLayer;
}
