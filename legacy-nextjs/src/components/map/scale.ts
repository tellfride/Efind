// Escalas visuais do mapa (puras — testadas em tests/map-scale.test.ts).
// Cor: do lilás claro ao índigo escuro da marca conforme a quantidade de eleitores do bairro.
// Raio: proporcional à raiz quadrada da quantidade (a ÁREA do círculo é proporcional ao total).

/** brand-200, brand-400, brand-500, brand-700, brand-900 */
export const COLOR_RAMP = ["#c7d2fe", "#818cf8", "#6366f1", "#4338ca", "#312e81"] as const;

export interface ColorBin {
  min: number;
  max: number;
  color: string;
}

function pickColor(ramp: readonly string[], index: number, classes: number): string {
  if (classes <= 1) return ramp[Math.min(ramp.length - 1, Math.floor((ramp.length - 1) * 0.75))];
  return ramp[Math.round((index * (ramp.length - 1)) / (classes - 1))];
}

/**
 * Faixas contíguas de 1 até maxCount (no máximo uma por cor da rampa). As faixas iniciais são mais
 * estreitas (escala quadrática), porque poucos bairros concentram muitos eleitores.
 */
export function buildColorScale(maxCount: number, ramp: readonly string[] = COLOR_RAMP): ColorBin[] {
  const max = Math.floor(maxCount);
  if (!Number.isFinite(max) || max < 1 || ramp.length === 0) return [];
  const classes = Math.min(ramp.length, max);
  const bins: ColorBin[] = [];
  let lower = 1;
  for (let i = 0; i < classes; i++) {
    const after = classes - i - 1; // faixas que ainda precisam de ao menos 1 valor cada
    const ideal = i === classes - 1 ? max : Math.round(max * ((i + 1) / classes) ** 2);
    const upper = Math.min(max - after, Math.max(lower, ideal));
    bins.push({ min: lower, max: upper, color: pickColor(ramp, i, classes) });
    lower = upper + 1;
  }
  return bins;
}

export function colorForCount(count: number, bins: readonly ColorBin[], ramp: readonly string[] = COLOR_RAMP): string {
  if (!bins.length) return pickColor(ramp, 0, 1);
  for (const bin of bins) if (count <= bin.max) return bin.color;
  return bins[bins.length - 1].color;
}

/** Rótulo da faixa para a legenda: "1", "2–5" */
export function binLabel(bin: ColorBin): string {
  const fmt = (n: number) => n.toLocaleString("pt-BR");
  return bin.min === bin.max ? fmt(bin.min) : `${fmt(bin.min)}–${fmt(bin.max)}`;
}

export const MIN_RADIUS = 6;
export const MAX_RADIUS = 30;

/** Raio (px) ∝ √count, com piso para continuar clicável no celular */
export function radiusForCount(
  count: number,
  maxCount: number,
  opts: { min?: number; max?: number } = {},
): number {
  const min = opts.min ?? MIN_RADIUS;
  const max = opts.max ?? MAX_RADIUS;
  if (!(maxCount > 0) || !(count > 0)) return min;
  const r = max * Math.sqrt(Math.min(count, maxCount) / maxCount);
  return Math.max(min, Math.round(r * 10) / 10);
}

/** Percentual de um total, protegido contra divisão por zero */
export function shareOf(count: number, total: number): number {
  return total > 0 ? (count / total) * 100 : 0;
}

/** Gradiente da camada de calor (do claro ao intenso) */
export const HEAT_GRADIENT: Record<number, string> = {
  0.2: "#a5b4fc",
  0.4: "#6366f1",
  0.6: "#4338ca",
  0.8: "#f59e0b",
  1: "#dc2626",
};
