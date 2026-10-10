"""Escalas visuais do mapa (lógica pura)."""

import math

from django.test import SimpleTestCase

from apps.mapview.scale import (
    COLOR_RAMP,
    MAX_RADIUS,
    MIN_RADIUS,
    build_color_scale,
    color_for_count,
    radius_for_count,
    share_of,
)


class ColorScaleTests(SimpleTestCase):
    def test_empty_when_no_data(self):
        for value in (0, -3, None, float("nan"), float("inf")):
            self.assertEqual(build_color_scale(value), [], value)

    def test_single_value_gets_one_bin(self):
        bins = build_color_scale(1)
        self.assertEqual(len(bins), 1)
        self.assertEqual((bins[0].min, bins[0].max), (1, 1))
        self.assertEqual(bins[0].label, "1")

    def test_bins_are_contiguous_and_cover_range(self):
        for maximum in (2, 3, 5, 6, 17, 240, 12_345):
            bins = build_color_scale(maximum)
            self.assertLessEqual(len(bins), len(COLOR_RAMP))
            self.assertEqual(bins[0].min, 1)
            self.assertEqual(bins[-1].max, maximum)
            for previous, current in zip(bins, bins[1:]):
                self.assertEqual(current.min, previous.max + 1)
            for b in bins:
                self.assertLessEqual(b.min, b.max)

    def test_colors_go_from_light_to_dark(self):
        bins = build_color_scale(100)
        self.assertEqual(len(bins), len(COLOR_RAMP))
        self.assertEqual(bins[0].color, COLOR_RAMP[0])
        self.assertEqual(bins[-1].color, COLOR_RAMP[-1])
        self.assertEqual([b.color for b in bins], list(COLOR_RAMP))

    def test_first_bins_are_narrower(self):
        bins = build_color_scale(100)
        widths = [b.max - b.min + 1 for b in bins]
        self.assertEqual(widths, sorted(widths))

    def test_labels_use_brazilian_thousands(self):
        bins = build_color_scale(5000)
        self.assertEqual(bins[-1].label.split("–")[1], "5.000")
        self.assertEqual(build_color_scale(3)[1].label, "2")

    def test_color_for_count(self):
        bins = build_color_scale(100)
        self.assertEqual(color_for_count(1, bins), bins[0].color)
        self.assertEqual(color_for_count(100, bins), bins[-1].color)
        self.assertEqual(color_for_count(10_000, bins), bins[-1].color)  # acima do máximo
        for b in bins:
            self.assertEqual(color_for_count(b.min, bins), b.color)
            self.assertEqual(color_for_count(b.max, bins), b.color)

    def test_color_without_bins_has_fallback(self):
        self.assertIn(color_for_count(5, []), COLOR_RAMP)

    def test_as_dict(self):
        self.assertEqual(
            build_color_scale(1)[0].as_dict(), {"min": 1, "max": 1, "color": build_color_scale(1)[0].color, "label": "1"}
        )


class RadiusTests(SimpleTestCase):
    def test_largest_gets_max_radius(self):
        self.assertEqual(radius_for_count(50, 50), MAX_RADIUS)

    def test_proportional_to_square_root(self):
        # 4x mais eleitores → o dobro do raio (a área do círculo é proporcional ao total)
        big = radius_for_count(400, 400)
        small = radius_for_count(100, 400)
        self.assertAlmostEqual(big / small, 2.0, places=1)

    def test_has_floor_for_tiny_neighborhoods(self):
        self.assertEqual(radius_for_count(1, 10_000), MIN_RADIUS)

    def test_degenerate_inputs_use_minimum(self):
        self.assertEqual(radius_for_count(0, 10), MIN_RADIUS)
        self.assertEqual(radius_for_count(5, 0), MIN_RADIUS)
        self.assertEqual(radius_for_count(-1, 10), MIN_RADIUS)
        self.assertEqual(radius_for_count(5, float("nan")), MIN_RADIUS)

    def test_count_above_max_is_clamped(self):
        self.assertEqual(radius_for_count(999, 100), MAX_RADIUS)

    def test_monotonic(self):
        radii = [radius_for_count(n, 200) for n in range(1, 201)]
        self.assertEqual(radii, sorted(radii))
        self.assertTrue(all(math.isfinite(r) for r in radii))


class ShareTests(SimpleTestCase):
    def test_share(self):
        self.assertEqual(share_of(25, 100), 25.0)
        self.assertAlmostEqual(share_of(1, 3), 33.333, places=2)

    def test_zero_total_is_safe(self):
        self.assertEqual(share_of(5, 0), 0.0)
