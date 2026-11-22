# -*- coding: utf-8 -*-
"""人物线稿、布料五层与材质表面规则的合成回归测试。"""
import sys
import unittest
from pathlib import Path

import numpy as np
from scipy.ndimage import distance_transform_edt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "common"))
sys.path.insert(0, str(ROOT / "tools" / "lib"))
sys.path.insert(0, str(ROOT / "tools" / "tachie"))

import drawing  # noqa: E402
import lint  # noqa: E402
import matregion  # noqa: E402
import schema  # noqa: E402


class LineDrawingTests(unittest.TestCase):
    def test_diagonal_five_pixel_line_uses_eight_neighbours(self):
        mask = np.zeros((9, 9), dtype=bool)
        mask[2:7, 2:7] = np.eye(5, dtype=bool)

        out = drawing.despeckle_lines(mask, min_size=5)

        self.assertEqual(out.sum(), 5)

    def test_protected_short_line_is_not_removed(self):
        mask = np.zeros((7, 7), dtype=bool)
        mask[2:4, 3] = True
        protected = np.zeros_like(mask)
        protected[2, 3] = True

        out = drawing.despeckle_lines(mask, min_size=4, protected=protected)

        self.assertTrue(out[2:4, 3].all())

    def test_line_kinds_are_mutually_exclusive(self):
        fg = np.ones((20, 20), dtype=bool)
        fg[:, 0] = False
        idx = np.ones(fg.shape, dtype=np.int16)
        idx[:, :9] = 0
        materials = [
            {"id": "hair", "role": "hair", "refs": []},
            {"id": "cloth", "role": "cloth", "refs": []},
        ]
        candidate = np.zeros(fg.shape, dtype=bool)
        candidate[2:18, 1] = True   # 外轮廓
        candidate[3:9, 5] = True    # 发丝
        candidate[3:9, 12] = True   # 内部结构

        layers = drawing.build_line_layers(
            candidate, fg, idx, materials, min_size=1)

        self.assertTrue(np.all(layers.kind[2:18, 1] == drawing.OUTLINE))
        self.assertTrue(np.all(layers.kind[3:9, 5] == drawing.STRANDS))
        self.assertTrue(np.all(layers.kind[3:9, 12] == drawing.STRUCTURE))
        values = layers.kind[layers.mask]
        self.assertTrue(np.all((values >= 1) & (values <= 3)))

    def test_material_seam_protects_short_structure(self):
        fg = np.ones((12, 12), dtype=bool)
        idx = np.zeros(fg.shape, dtype=np.int16)
        idx[:, 6:] = 1
        materials = [
            {"id": "blouse", "role": "white", "refs": []},
            {"id": "collar", "role": "cloth", "refs": []},
        ]
        candidate = np.zeros(fg.shape, dtype=bool)
        candidate[4:6, 6] = True

        layers = drawing.build_line_layers(
            candidate, fg, idx, materials, min_size=4)

        self.assertTrue(layers.mask[4:6, 6].all())
        self.assertTrue(layers.protected[4:6, 6].all())


class ClothDrawingTests(unittest.TestCase):
    def setUp(self):
        self.rgb = np.full((60, 60, 3), (153, 136, 119), dtype=np.uint8)
        self.fg = np.ones((60, 60), dtype=bool)
        self.idx = np.zeros((60, 60), dtype=np.int16)
        self.materials = [
            {"id": "skirt", "role": "cloth", "group": "uniform",
             "refs": ["#998877", "#444433"]},
        ]

    def test_no_anchor_generates_no_fold(self):
        layers = drawing.build_cloth_layers(
            self.rgb, self.fg, self.idx, self.materials)

        self.assertFalse(layers.fold.any())
        self.assertFalse(layers.occlusion.any())
        self.assertTrue(layers.base.any())

    def test_radiating_skirt_folds_have_independent_paths(self):
        config = {"folds": [
            {"material": "skirt", "kind": "radiate",
             "from": [0.30, 0.10], "to": [0.20, 0.90], "width": 4, "tone": 1},
            {"material": "skirt", "kind": "radiate",
             "from": [0.70, 0.10], "to": [0.85, 0.72], "width": 2, "tone": 1},
        ]}

        layers = drawing.build_cloth_layers(
            self.rgb, self.fg, self.idx, self.materials, config)

        self.assertTrue(layers.fold.any())
        self.assertEqual(len(layers.stats["folds"]), 2)
        self.assertTrue(all(item["anchor_hit"] for item in layers.stats["folds"]))
        self.assertNotEqual(layers.stats["folds"][0]["pixels"],
                            layers.stats["folds"][1]["pixels"])
        ys, _ = np.where(layers.fold)
        self.assertLess(ys.min(), 10)
        self.assertGreater(ys.max(), 40)

    def test_occlusion_only_lands_on_under_material(self):
        idx = self.idx.copy()
        idx[30:] = 1
        rgb = self.rgb.copy()
        rgb[30:] = 255
        materials = [
            {"id": "collar", "role": "cloth", "refs": ["#998877", "#666655"]},
            {"id": "blouse", "role": "white", "refs": ["#ffffff", "#ddcccc"]},
        ]
        config = {"occlusions": [{"over": "collar", "under": "blouse", "width": 2}]}

        layers = drawing.build_cloth_layers(rgb, self.fg, idx, materials, config)

        self.assertTrue(layers.occlusion.any())
        self.assertFalse((layers.occlusion & (idx == 0)).any())
        self.assertTrue((layers.occlusion & (idx == 1)).any())

    def test_colored_fold_does_not_become_black(self):
        pal = np.array([(0, 0, 0), (153, 136, 119), (68, 68, 51)], dtype=np.uint8)
        config = {"folds": [{"material": "skirt", "kind": "radiate",
                             "from": [0.5, 0.1], "to": [0.5, 0.9],
                             "width": 4, "tone": 1}]}

        fills, _, debug = matregion.render_spec(
            self.rgb, self.fg, pal, self.materials, return_debug=True,
            drawing_config=config)
        fold = debug["cloth_layers"]["fold"]

        self.assertTrue(fold.any())
        self.assertTrue(np.all(fills[fold] == (68, 68, 51)))
        self.assertFalse(np.any(np.all(fills[fold] == 0, axis=-1)))


class SurfaceDrawingTests(unittest.TestCase):
    def setUp(self):
        self.rgb = np.full((50, 50, 3), (153, 136, 119), dtype=np.uint8)
        self.fg = np.ones((50, 50), dtype=bool)
        self.idx = np.zeros((50, 50), dtype=np.int16)
        self.materials = [
            {"id": "cloth", "role": "cloth", "refs": ["#998877", "#666655"]},
        ]

    def test_plaid_is_warped_by_fold_field(self):
        surface = {"materials": {"cloth": {
            "surface": "plaid", "spacing": [6, 7], "axis": [1, 0],
            "tones": [1], "line_width": 1,
        }}}
        fold = {"material": "cloth", "kind": "radiate",
                "from": [0.3, 0.1], "to": [0.7, 0.9], "width": 5, "tone": 1}

        plain = drawing.build_cloth_layers(
            self.rgb, self.fg, self.idx, self.materials, surface)
        warped = drawing.build_cloth_layers(
            self.rgb, self.fg, self.idx, self.materials,
            {**surface, "folds": [fold]})

        self.assertTrue(plain.surface["cloth"].any())
        self.assertFalse(np.array_equal(plain.surface["cloth"], warped.surface["cloth"]))
        self.assertTrue(np.all(warped.surface_tones["cloth"][warped.surface["cloth"]] == 1))

    def test_fur_grain_only_uses_material_edge(self):
        config = {"materials": {"cloth": {
            "surface": "fur", "edge_width": 2, "tone": 1,
        }}}

        layers = drawing.build_cloth_layers(
            self.rgb, self.fg, self.idx, self.materials, config)
        fur = layers.surface["cloth"]

        self.assertTrue(fur.any())
        self.assertFalse((fur & (distance_transform_edt(self.idx == 0) > 2)).any())

    def test_swimwear_arc_and_missing_highlight_tone(self):
        arc = {"path": [[0.2, 0.3], [0.5, 0.2], [0.8, 0.3]],
               "width": 2, "tone": 0}
        config = {"materials": {"cloth": {"surface": "swimwear", "arcs": [arc]}}}

        layers = drawing.build_cloth_layers(
            self.rgb, self.fg, self.idx, self.materials, config)
        self.assertTrue(layers.surface["cloth"].any())

        arc.pop("tone")
        skipped = drawing.build_cloth_layers(
            self.rgb, self.fg, self.idx, self.materials, config)
        self.assertFalse(skipped.surface["cloth"].any())


class DrawingValidationTests(unittest.TestCase):
    def setUp(self):
        self.materials = [
            {"id": "cloth", "role": "cloth", "refs": ["#998877", "#666655"]},
            {"id": "blouse", "role": "white", "refs": ["#ffffff", "#ddcccc"]},
        ]
        self.fold = {"material": "cloth", "kind": "radiate",
                     "from": [0.4, 0.1], "to": [0.6, 0.9],
                     "width": 3, "tone": 1}

    def test_schema_accepts_valid_drawing_config(self):
        schema.validate_drawing({"folds": [self.fold]}, self.materials)

    def test_schema_rejects_unnormalised_anchor(self):
        self.fold["from"] = [20, 30]
        with self.assertRaisesRegex(ValueError, "归一化"):
            schema.validate_drawing({"folds": [self.fold]}, self.materials)

    def test_schema_rejects_tone_outside_existing_refs(self):
        self.fold["tone"] = 2
        with self.assertRaisesRegex(ValueError, "refs"):
            schema.validate_drawing({"folds": [self.fold]}, self.materials)

    def test_schema_rejects_unknown_surface(self):
        config = {"materials": {"cloth": {"surface": "velvet"}}}
        with self.assertRaisesRegex(ValueError, "surface"):
            schema.validate_drawing(config, self.materials)

    def test_lint_reports_missing_fold_and_illegal_black(self):
        idx = np.zeros((20, 20), dtype=np.int16)
        fills = np.full((20, 20, 3), (153, 136, 119), dtype=np.uint8)
        fills[5, 5] = 0
        layers = {name: np.zeros((20, 20), dtype=bool) for name in
                  ("base", "form", "fold", "occlusion", "highlight")}
        layers["fold"][5, 5] = True
        report = {"folds": [{"anchor_hit": False, "pixels": 0}]}

        result = lint.lint_drawing(
            fills, idx, self.materials[:1], layers, report,
            config={"folds": [self.fold]}, line_mask=np.zeros((20, 20), bool))

        self.assertFalse(result["checks"]["drawing_fold_anchors"]["pass"])
        self.assertFalse(result["checks"]["drawing_cloth_black"]["pass"])
        self.assertTrue(result["checks"]["drawing_layer_bounds"]["pass"])


if __name__ == "__main__":
    unittest.main()
