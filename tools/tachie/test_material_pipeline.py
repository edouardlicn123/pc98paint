# -*- coding: utf-8 -*-
"""材质分类、语义验收与色板合并的回归测试。"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "common"))
sys.path.insert(0, str(ROOT / "tools" / "lib"))
sys.path.insert(0, str(ROOT / "tools" / "tachie"))

import asset3  # noqa: E402
import drawing  # noqa: E402
import lint  # noqa: E402
import matregion  # noqa: E402
import palette_for  # noqa: E402
import pc98_sprite_v7 as v7  # noqa: E402
from PIL import Image  # noqa: E402


MATERIALS = [
    {"id": "skin", "role": "skin", "refs": ["#f6d9c8"]},
    {"id": "blouse", "role": "white", "refs": ["#ffffff"]},
    {"id": "iris", "role": "eye", "refs": ["#2f8f86"]},
]


class MaterialLintTests(unittest.TestCase):
    def test_skin_enclosed_white_region_fails(self):
        idx = np.zeros((40, 40), dtype=np.int16)
        idx[16:24, 16:24] = 1
        fg = np.ones(idx.shape, dtype=bool)

        report = lint.lint_materials(idx, MATERIALS, fg)

        self.assertFalse(report["pass"])
        self.assertFalse(report["checks"]["skin_white_holes"]["pass"])
        self.assertEqual(report["checks"]["skin_white_holes"]["value"], 64)

    def test_eye_adjacent_white_highlight_is_exempt(self):
        idx = np.zeros((40, 40), dtype=np.int16)
        idx[16:22, 16:22] = 1
        idx[16:22, 22:27] = 2
        fg = np.ones(idx.shape, dtype=bool)

        report = lint.lint_materials(idx, MATERIALS, fg)

        self.assertTrue(report["checks"]["skin_white_holes"]["pass"])
        self.assertEqual(report["checks"]["skin_white_holes"]["value"], 0)

    def test_nearby_eye_does_not_exempt_unrelated_skin_white_hole(self):
        idx = np.zeros((40, 40), dtype=np.int16)
        idx[16:22, 16:22] = 1
        idx[16:22, 25:27] = 2  # 靠近但隔着皮肤，不在白块边缘上。
        fg = np.ones(idx.shape, dtype=bool)

        report = lint.lint_materials(idx, MATERIALS, fg)

        self.assertFalse(report["checks"]["skin_white_holes"]["pass"])
        self.assertEqual(report["checks"]["skin_white_holes"]["value"], 36)

    def test_material_area_baseline_detects_large_changes(self):
        idx = np.zeros((20, 20), dtype=np.int16)
        idx[:, 10:] = 1
        fg = np.ones(idx.shape, dtype=bool)
        baseline = {
            "expected": {"skin": 200, "blouse": 200, "iris": 0},
            "tolerance": 0.35,
        }

        passing = lint.lint_materials(idx, MATERIALS, fg, baseline)
        self.assertTrue(passing["checks"]["material_area"]["pass"])

        idx[:, 5:] = 1
        failing = lint.lint_materials(idx, MATERIALS, fg, baseline)
        self.assertFalse(failing["checks"]["material_area"]["pass"])
        self.assertGreater(
            failing["checks"]["material_area"]["deviations"]["blouse"], 0.35)


class MaterialClassificationTests(unittest.TestCase):
    def setUp(self):
        self.skin_white = [
            {"id": "skin", "role": "skin",
             "refs": ["#f6d9c8", "#e8b39c", "#b57a6a"]},
            {"id": "blouse", "role": "white", "refs": ["#ffffff", "#dcd3c6"]},
        ]

    def test_pale_skin_recovery_does_not_recolor_large_white_cloth(self):
        rgb = np.empty((40, 80, 3), dtype=np.uint8)
        rgb[:, :40] = (246, 217, 200)
        rgb[:, 40:] = 255
        rgb[16:20, 16:20] = (228, 214, 202)
        fg = np.ones(rgb.shape[:2], dtype=bool)

        idx, debug = matregion.classify_materials(
            rgb, fg, self.skin_white, tier="half", return_debug=True)

        self.assertTrue(np.all(idx[16:20, 16:20] == 0))
        self.assertTrue(np.all(idx[:, 40:] == 1))
        self.assertGreater(debug["report"]["overrides"]["skin_recovery"], 0)
        self.assertIn("raw_stats", debug["report"])
        self.assertIn("final_stats", debug["report"])

    def test_teal_iris_dark_lines_and_tiny_highlight_are_protected(self):
        materials = self.skin_white + [
            {"id": "iris", "role": "eye", "refs": ["#2f8f86", "#1f5f5a"]}]
        rgb = np.full((40, 40, 3), (246, 217, 200), dtype=np.uint8)
        rgb[11:29, 11:29] = 0
        rgb[12:28, 12:28] = (47, 143, 134)
        rgb[18:20, 18:20] = 255
        fg = np.ones(rgb.shape[:2], dtype=bool)

        idx, debug = matregion.classify_materials(
            rgb, fg, materials, tier="full", return_debug=True)

        self.assertTrue(np.all(idx[12:28, 12] == 2))
        self.assertTrue(np.all(idx[18:20, 18:20] == 1))
        self.assertTrue(np.all(idx[11, 11:29] == -1))
        self.assertTrue(np.all(debug["override_masks"]["eye_highlight"][18:20, 18:20]))
        self.assertLess(debug["report"]["thresholds"]["fragment_max"], 12)

    def test_uniform_group_does_not_create_internal_seam_shadow(self):
        materials = [
            {"id": "collar", "role": "cloth", "group": "uniform",
             "refs": ["#998877", "#666655"]},
            {"id": "skirt", "role": "cloth", "group": "uniform",
             "refs": ["#887766", "#444433"]},
        ]
        rgb = np.empty((40, 40, 3), dtype=np.uint8)
        rgb[:20] = (153, 136, 119)
        rgb[20:] = (136, 119, 102)
        fg = np.ones(rgb.shape[:2], dtype=bool)
        pal = np.array([
            (0, 0, 0), (255, 255, 255), (153, 136, 119),
            (136, 119, 102), (102, 102, 85), (68, 68, 51),
        ], dtype=np.uint8)

        fills, _ = matregion.render_spec(rgb, fg, pal, materials)

        np.testing.assert_array_equal(fills[19, 4], (153, 136, 119))
        np.testing.assert_array_equal(fills[20, 4], (136, 119, 102))


class MaterialDespeckleTests(unittest.TestCase):
    def test_small_color_component_cannot_cross_material_boundary(self):
        fills = np.full((5, 5, 3), 100, dtype=np.uint8)
        fills[2, 2] = 255
        material_idx = np.ones((5, 5), dtype=np.int16)
        material_idx[2, 2] = 0

        out = asset3.despeckle_colors(fills, 2, material_idx=material_idx)

        np.testing.assert_array_equal(out[2, 2], (255, 255, 255))

    def test_protected_eye_highlight_is_not_despeckled(self):
        fills = np.full((5, 5, 3), 100, dtype=np.uint8)
        fills[2, 2] = 255
        protect = np.zeros((5, 5), dtype=bool)
        protect[2, 2] = True

        out = asset3.despeckle_colors(fills, 2, protect=protect)

        np.testing.assert_array_equal(out[2, 2], (255, 255, 255))


class PaletteSafetyTests(unittest.TestCase):
    def test_momo_palette_slots_stay_unchanged_and_have_mapping(self):
        spec = json.loads((ROOT / "characters" / "momo" / "spec.json").read_text(
            encoding="utf-8"))
        approved = json.loads((ROOT / "characters" / "momo" / "palette.json").read_text(
            encoding="utf-8"))

        payload = palette_for.build_palette(spec)

        self.assertEqual(payload["colors"], approved["colors"])
        self.assertEqual(payload["slots"], approved["slots"])
        self.assertEqual(set(payload["mapping"]), {m["id"] for m in spec["materials"]})
        for material in spec["materials"]:
            for ref in material["refs"]:
                self.assertIn(payload["mapping"][material["id"]][ref], payload["slots"])

    def test_overflow_cannot_merge_protected_skin_hair_or_eye_tones(self):
        refs = []
        for i in range(1, 20):
            refs.append("#%02x%02x%02x" % (
                (i * 13) % 256, (i * 29) % 256, (i * 47) % 256))
        spec = {
            "id": "overflow",
            "materials": [
                {"id": "skin", "role": "skin", "refs": refs[:7]},
                {"id": "hair", "role": "hair", "refs": refs[7:13]},
                {"id": "iris", "role": "eye", "refs": refs[13:]},
            ],
        }

        with self.assertRaisesRegex(ValueError, "人工评审"):
            palette_for.build_palette(spec)


class LineLayerTests(unittest.TestCase):
    def test_white_cloth_shadow_needs_nearby_ink_core(self):
        mid = np.full((24, 24, 3), 255, dtype=np.uint8)
        mid[2:22, 8:10] = 180  # 浅灰阴影：有对比度，但没有深色线芯。
        mid[2:22, 16] = 20     # 真正的深色细线必须保留。
        strict_mask = np.ones((24, 24), dtype=bool)

        original, _ = v7.line_layer(Image.fromarray(mid), (12, 12), contrast=30)
        fixed, _ = v7.line_layer(
            Image.fromarray(mid), (12, 12), contrast=30, strict_mask=strict_mask)

        self.assertTrue(original[:, 4:6].any(), "测试夹具应能复现灰影误提线")
        self.assertFalse(fixed[:, 4:6].any(), "灰影不得独立形成黑线")
        self.assertTrue(fixed[:, 8].any(), "真实深色细线必须保留")

    def test_white_strict_mask_preserves_boundaries(self):
        materials = [
            {"id": "blouse", "role": "white", "refs": []},
            {"id": "skin", "role": "skin", "refs": []},
        ]
        idx = np.zeros((101, 101), dtype=np.int16)
        idx[:, 90] = 1
        fg = np.ones((101, 101), dtype=bool)
        fg[0, :] = False

        strict = drawing.white_line_strict_mask(idx, fg, materials)

        self.assertTrue(strict[50, 50], "宽阔白衣内部应过滤灰影")
        self.assertFalse(strict[50, 85], "皮肤/衣袖边界附近必须保留原提线")
        self.assertFalse(strict[5, 50], "人物外轮廓附近必须保留原提线")


@unittest.skipUnless(
    (ROOT / "characters" / "momo" / "girl_v3_half_hi.jpg").exists(),
    "缺少 momo 固定回归源图")
class MomoRegressionTests(unittest.TestCase):
    def test_fixed_sample_materials_and_palette_assignments(self):
        spec = json.loads((ROOT / "characters" / "momo" / "spec.json").read_text(
            encoding="utf-8"))
        palette = json.loads((ROOT / "characters" / "momo" / "palette.json").read_text(
            encoding="utf-8"))
        baseline = spec["checks"]["material_area"]["half"]
        with mock.patch.object(asset3.Image.Image, "save", autospec=True):
            _, debug = asset3.render(
                ROOT / baseline["source"], "half", "test_momo_regression",
                np.array(palette["colors"], dtype=np.uint8),
                material_region=True, materials=spec["materials"],
                material_baseline=baseline, drawing_config=spec["drawing"],
                return_debug=True)
            _, baseline_debug = asset3.render(
                ROOT / baseline["source"], "half", "test_momo_regression_base",
                np.array(palette["colors"], dtype=np.uint8),
                material_region=True, materials=spec["materials"],
                material_baseline=baseline, return_debug=True)

        self.assertTrue(debug["material_report"]["pass"], debug["material_report"])
        np.testing.assert_array_equal(debug["material_idx"], baseline_debug["material_idx"])
        self.assertTrue(all(item["anchor_hit"] and item["pixels"] > 0
                            for item in debug["drawing_report"]["folds"]))
        collar_id = next(i for i, m in enumerate(spec["materials"])
                         if m["id"] == "collar")
        skirt_fold = debug["cloth_layers"]["fold"].copy()
        skirt_fold[:280] = False
        self.assertGreater((skirt_fold & (debug["material_idx"] == collar_id)).sum(), 300)
        self.assertGreater(debug["cloth_layers"]["occlusion"].sum(), 0)
        self.assertFalse(debug["line_mask"][222:233, 101:111].any(),
                         "左胸无深色线芯的灰影不得再次变成黑线")
        self.assertGreaterEqual(debug["line_mask"][159:201, 62:68].sum(), 46,
                                "左侧手臂/衣袖长线不得被灰影过滤删除")
        self.assertGreaterEqual(debug["line_mask"][163:196, 182:202].sum(), 58,
                                "右侧手臂/衣袖长线不得被灰影过滤删除")
        self.assertGreaterEqual(debug["line_mask"][45:49, 165:169].sum(), 5,
                                "顶部对角发丝不得被四邻域误删")
        self.assertGreaterEqual(debug["line_mask"][39:44, 127:132].sum(), 5,
                                "刘海对角发丝不得被四邻域误删")
        idx = debug["material_idx"]
        fills = debug["fills"]
        material_ids = {m["id"]: i for i, m in enumerate(spec["materials"])}

        skin = fills[idx == material_ids["skin"]]
        self.assertFalse(np.any(np.all(skin == (255, 255, 255), axis=1)),
                         "皮肤/下巴区域不得出现纯白色")

        blouse = fills[idx == material_ids["blouse"]]
        self.assertTrue(np.any(np.all(blouse == (255, 255, 255), axis=1)),
                        "白衣必须保留纯白色")

        iris = fills[idx == material_ids["iris"]]
        iris_colors = {tuple(map(int, c)) for c in np.unique(iris.reshape(-1, 3), axis=0)}
        self.assertTrue(iris_colors <= {(0, 0, 0), (51, 136, 136), (34, 102, 85)})
        self.assertTrue(iris_colors & {(51, 136, 136), (34, 102, 85)})

        expected_uniform = {
            "collar": {(0, 0, 0), (153, 136, 119), (102, 102, 85)},
            "skirt": {(0, 0, 0), (153, 136, 119), (68, 68, 51)},
        }
        for mid, allowed in expected_uniform.items():
            pixels = fills[idx == material_ids[mid]]
            colors = {tuple(map(int, c)) for c in np.unique(pixels.reshape(-1, 3), axis=0)}
            self.assertTrue(colors <= allowed, (mid, colors))


if __name__ == "__main__":
    unittest.main()
