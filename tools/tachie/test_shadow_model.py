# -*- coding: utf-8 -*-
"""Unified shadow model: light direction, local scale, cast and spatial priors."""
import sys
import unittest
from pathlib import Path

import numpy as np
from scipy.ndimage import distance_transform_edt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "common"))
sys.path.insert(0, str(ROOT / "tools" / "lib"))
sys.path.insert(0, str(ROOT / "tools" / "tachie"))

import matregion  # noqa: E402
import shading  # noqa: E402


class DirectionalBandTests(unittest.TestCase):
    def setUp(self):
        self.light = shading.light_vector("upper-left")

    def test_band_sits_on_the_side_away_from_the_light(self):
        mask = np.zeros((60, 100), dtype=bool)
        mask[10:50, 10:90] = True
        mid, deep, _ = shading.directional_bands(
            mask, self.light, (0.5, 0.25), min_px=5)
        self.assertTrue(mid.any())
        ys, xs = np.where(mask)
        my, mx = np.where(mid)
        self.assertGreater(mx.mean(), xs.mean() + 5.0)
        self.assertLess(int(mid[:, :40].sum()), int(mid[:, 60:].sum()))

    def test_deep_is_nested_in_mid(self):
        mask = np.zeros((60, 100), dtype=bool)
        mask[5:55, 5:95] = True
        mid, deep, core = shading.directional_bands(
            mask, self.light, (0.6, 0.3, 0.12), min_px=3)
        self.assertFalse(np.any(deep & ~mid))
        self.assertFalse(np.any(core & ~deep))

    def test_local_scale_not_global_width(self):
        small = np.zeros((80, 80), dtype=bool)
        small[30:50, 35:45] = True
        large = np.zeros((80, 80), dtype=bool)
        large[10:70, 10:70] = True
        sm, _, _ = shading.directional_bands(
            small, self.light, (0.5,), min_px=2)
        lm, _, _ = shading.directional_bands(
            large, self.light, (0.5,), min_px=2)
        small_depth = distance_transform_edt(small)[sm].max()
        large_depth = distance_transform_edt(large)[lm].max()
        self.assertGreater(large_depth, small_depth * 2.0,
                           "band must scale with the local inscribed radius")

    def test_cast_shadow_projects_down_right(self):
        source = np.zeros((80, 80), dtype=bool)
        source[10:20, 10:40] = True
        receiver = np.zeros((80, 80), dtype=bool)
        receiver[10:70, 10:60] = True
        cast = shading.cast_shadow(source, receiver, self.light, depth=4)
        self.assertTrue(cast.any())
        self.assertFalse(np.any(cast & source))
        ys, xs = np.where(cast)
        self.assertGreater(ys.mean(), 18.0)
        self.assertGreater(xs.mean(), 24.0)


class ContinuousBodyFieldTests(unittest.TestCase):
    def setUp(self):
        self.light = shading.light_vector("upper-left")

    def test_each_leg_gets_its_own_right_cylinder_band(self):
        mask = np.zeros((80, 90), dtype=bool)
        mask[10:70, 10:25] = True
        mask[10:70, 55:70] = True
        mid, deep, _ = shading.continuous_bands(
            mask, self.light, thresholds=(0.35, 0.82), min_px=3)
        self.assertTrue(mid[:, 10:25].any())
        self.assertTrue(mid[:, 55:70].any())
        self.assertFalse(mid[:, 10:15].any())
        self.assertFalse(mid[:, 55:60].any())
        self.assertFalse(np.any(deep & ~mid))

    def test_band_continues_through_changing_torso_width(self):
        mask = np.zeros((90, 100), dtype=bool)
        mask[10:35, 20:80] = True
        mask[35:60, 35:65] = True
        mask[60:80, 25:75] = True
        field = shading.cylindrical_field(mask, self.light)
        mid, _, _ = shading.field_bands(
            field, mask, thresholds=(0.35,), min_px=3)
        for y in (20, 45, 70):
            self.assertTrue(mid[y].any())
            self.assertGreater(np.where(mid[y])[0].mean(),
                               np.where(mask[y])[0].mean())

    def test_larger_ellipsoid_terminator_expands_shadow_area(self):
        mask = np.zeros((80, 80), dtype=bool)
        mask[5:75, 5:75] = True
        small = shading.ellipsoid_field(
            mask, 40, 40, 30, 30, self.light, terminator=0.35)
        large = shading.ellipsoid_field(
            mask, 40, 40, 30, 30, self.light, terminator=0.65)
        small_mid = mask & (small >= 0.30)
        large_mid = mask & (large >= 0.30)
        self.assertGreater(large_mid.sum(), small_mid.sum())


class SpatialPriorTests(unittest.TestCase):
    def test_isolated_lower_hair_island_returns_to_skin(self):
        materials = [
            {"id": "skin", "role": "skin", "refs": ["#ffddcc", "#d99a7e"]},
            {"id": "hair", "role": "hair", "refs": ["#ffffff", "#f7b8a8"]},
        ]
        rgb = np.full((100, 80, 3), (255, 221, 204), dtype=np.uint8)
        rgb[:60, 10:70] = (247, 184, 168)
        rgb[30:40, 20:60] = (255, 221, 204)
        rgb[80:90, 30:50] = (229, 162, 153)  # thigh island in the lower body
        fg = np.ones((100, 80), dtype=bool)

        idx = matregion.classify_materials(rgb, fg, materials, tier="half")

        self.assertTrue(np.all(idx[80:90, 30:50] == 0),
                        "lower-body island must not stay hair")


if __name__ == "__main__":
    unittest.main()
