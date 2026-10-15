"""Escalas visuais do mapa (lógica pura).

Cor: do lilás claro ao índigo escuro da marca conforme a quantidade de apoiadores do bairro.
Raio: proporcional à raiz quadrada da quantidade (a ÁREA do círculo é proporcional ao total).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

# brand-200, brand-400, brand-500, brand-700, brand-900
COLOR_RAMP: tuple[str, ...] = ("#c7d2fe", "#818cf8", "#6366f1", "#4338ca", "#312e81")

MIN_RADIUS = 6.0
MAX_RADIUS = 30.0


def _round_half_up(value: float) -> int:
    """Arredondamento "comercial" (o `round` do Python arredonda .5 para o par mais próximo)."""
    return int(math.floor(value + 0.5))


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


@dataclass(frozen=True)
class ColorBin:
    min: int
    max: int
    color: str

    @property
    def label(self) -> str:
        """Rótulo da faixa para a legenda: "1", "2–5"."""
        return _fmt_int(self.min) if self.min == self.max else f"{_fmt_int(self.min)}–{_fmt_int(self.max)}"

    def as_dict(self) -> dict:
        return {"min": self.min, "max": self.max, "color": self.color, "label": self.label}


def _pick_color(ramp: Sequence[str], index: int, classes: int) -> str:
    if classes <= 1:
        return ramp[min(len(ramp) - 1, int(math.floor((len(ramp) - 1) * 0.75)))]
    return ramp[_round_half_up(index * (len(ramp) - 1) / (classes - 1))]


def build_color_scale(max_count: float, ramp: Sequence[str] = COLOR_RAMP) -> list[ColorBin]:
    """Faixas contíguas de 1 até `max_count` (no máximo uma por cor da rampa).

    As faixas iniciais são mais estreitas (escala quadrática), porque poucos bairros concentram muitos apoiadores.
    """
    try:
        maximum = int(math.floor(max_count))
    except (TypeError, ValueError, OverflowError):  # None, NaN, infinito
        return []
    if maximum < 1 or not ramp:
        return []
    classes = min(len(ramp), maximum)
    bins: list[ColorBin] = []
    lower = 1
    for i in range(classes):
        after = classes - i - 1  # faixas que ainda precisam de ao menos 1 valor cada
        ideal = maximum if i == classes - 1 else _round_half_up(maximum * ((i + 1) / classes) ** 2)
        upper = min(maximum - after, max(lower, ideal))
        bins.append(ColorBin(lower, upper, _pick_color(ramp, i, classes)))
        lower = upper + 1
    return bins


def color_for_count(count: float, bins: Sequence[ColorBin], ramp: Sequence[str] = COLOR_RAMP) -> str:
    if not bins:
        return _pick_color(ramp, 0, 1)
    for b in bins:
        if count <= b.max:
            return b.color
    return bins[-1].color


def radius_for_count(count: float, max_count: float, *, min_radius: float = MIN_RADIUS, max_radius: float = MAX_RADIUS) -> float:
    """Raio (px) proporcional a √count, com piso para o círculo continuar clicável no celular."""
    if not (max_count > 0) or not (count > 0):
        return min_radius
    radius = max_radius * math.sqrt(min(count, max_count) / max_count)
    return max(min_radius, _round_half_up(radius * 10) / 10)


def share_of(count: float, total: float) -> float:
    """Percentual de um total, protegido contra divisão por zero."""
    return (count / total) * 100 if total > 0 else 0.0
