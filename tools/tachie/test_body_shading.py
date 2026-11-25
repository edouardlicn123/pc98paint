# -*- coding: utf-8 -*-
"""结构派生遮挡（layer_edge）、胸围阴影与 prompt 体型参数化测试。"""
import json
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
import prompt  # noqa: E402
import schema  # noqa: E402


def _cloth_materials():
    return [
        {"id": "coat", "role": "cloth",
         "refs": ["#4466aa", "#224477", "#223355"]},
        {"id": "blouse", "role": "white", "refs": ["#ffffff", "#ddddbb"]},
    ]


class LayerEdgeTests(unittest.TestCase):
    def setUp(self):
        shape = (40, 40)
        self.fg = np.ones(shape, dtype=bool)
        self.rgb = np.full(shape + (3,), (153, 136, 119), dtype=np.uint8)
        self.idx = np.zeros(shape, dtype=np.int16)
        self.idx[:, 20:] = 1
        self.materials = _cloth_materials()

    def test_layer_edge_band_stays_inside_under_and_near_seam(self):
        config = {"occlusions": [{
            "over": "coat", "under": "blouse",
            "derive": "layer_edge", "width": 2, "tone": 1,
        }]}

        layers = drawing.build_cloth_layers(
            self.rgb, self.fg, self.idx, self.materials, config)

        band = layers.occlusion
        self.assertTrue(band.any())
        self.assertFalse((band & (self.idx == 0)).any(),
                         "阴影不得越界到 over 材质")
        distance = distance_transform_edt(self.idx != 0)
        self.assertLessEqual(float(distance[band].max()), 3.0)
        self.assertGreaterEqual(float(distance[band].max()), 1.0)

    def test_legacy_dilation_branch_remains_available(self):
        config = {"occlusions": [{
            "over": "coat", "under": "blouse", "width": 2, "tone": 1,
        }]}

        layers = drawing.build_cloth_layers(
            self.rgb, self.fg, self.idx, self.materials, config)

        self.assertTrue(layers.occlusion.any())
        self.assertEqual(layers.stats["occlusions"][0]["derive"], "dilate")


class BustShadingTests(unittest.TestCase):
    def setUp(self):
        shape = (100, 100)
        self.fg = np.ones(shape, dtype=bool)
        self.rgb = np.full(shape + (3,), (255, 255, 255), dtype=np.uint8)
        self.white = np.zeros(shape, dtype=bool)
        self.white[15:90, 15:85] = True
        self.idx = np.where(self.white, 1, 0).astype(np.int16)
        self.materials = _cloth_materials()

    def body(self, size, lean=0.0):
        return {
            "bust": {"size": size, "center_y_head": 2.5,
                     "separation": 0.55,
                     "under_boob_y_head": 3.05 if size else None},
            "torso": {"lean": lean},
        }

    def test_flat_bust_has_no_lobes_and_large_bust_has_volume_and_cast(self):
        flat = drawing.build_cloth_layers(
            self.rgb, self.fg, self.idx, self.materials,
            body=self.body(0))
        full = drawing.build_cloth_layers(
            self.rgb, self.fg, self.idx, self.materials,
            body=self.body(3))

        self.assertEqual(flat.stats["body"]["lobes"], [])
        self.assertGreater(full.stats["body"]["form_pixels"], 50)
        self.assertGreater(full.stats["body"]["cast_pixels"], 0)
        self.assertGreater(full.form.sum(), flat.form.sum())
        blouse_form = full.form & (self.idx == 1)
        self.assertFalse((blouse_form & ~self.white).any())

    def test_bust_center_is_57_percent_from_shoulder_to_waist(self):
        layers = drawing.build_cloth_layers(
            self.rgb, self.fg, self.idx, self.materials,
            body=self.body(2))
        model = layers.stats["body"]
        expected = model["shoulder_y"] + 0.57 * (
            model["waist_y"] - model["shoulder_y"])
        self.assertAlmostEqual(model["center_y"], expected, places=2)

    def test_torso_lean_shifts_lobe_centers(self):
        upright = drawing.build_cloth_layers(
            self.rgb, self.fg, self.idx, self.materials,
            body=self.body(3, lean=0.0))
        leaning = drawing.build_cloth_layers(
            self.rgb, self.fg, self.idx, self.materials,
            body=self.body(3, lean=0.3))

        cx_upright = np.mean([v[0] for v in upright.stats["body"]["lobes"]])
        cx_leaning = np.mean([v[0] for v in leaning.stats["body"]["lobes"]])
        self.assertGreater(cx_leaning, cx_upright + 2.0)

    def test_lobes_stay_inside_torso_band(self):
        layers = drawing.build_cloth_layers(
            self.rgb, self.fg, self.idx, self.materials,
            body=self.body(3))
        model = layers.stats["body"]
        for cx, _cy, rx, _ry in model["lobes"]:
            self.assertGreaterEqual(cx - rx, model["torso_left"] - 0.01)
            self.assertLessEqual(cx + rx, model["torso_right"] + 0.01)

    def test_inner_skin_does_not_shrink_torso_band(self):
        # Hands/folds classified as skin sit inside the blouse silhouette; the
        # torso band must follow the sleeve-relative width, not those edges.
        materials = _cloth_materials() + [
            {"id": "skin", "role": "skin", "refs": ["#f0d0b0"]}]
        idx = self.idx.copy()
        idx[55:75, 25:32] = 2
        idx[55:75, 68:75] = 2

        wide = drawing.build_cloth_layers(
            self.rgb, self.fg, self.idx, materials, body=self.body(2))
        narrow = drawing.build_cloth_layers(
            self.rgb, self.fg, idx, materials, body=self.body(2))

        self.assertEqual(narrow.stats["body"]["arm_source"], "ratio")
        self.assertAlmostEqual(narrow.stats["body"]["torso_width"],
                               wide.stats["body"]["torso_width"], places=2)

    def test_tilted_torso_staggers_lobe_centers(self):
        # A parallelogram torso makes the sway axis non-vertical; the chest
        # pair must ride along the perpendicular instead of staying level.
        white = np.zeros((100, 100), dtype=bool)
        for y in range(15, 90):
            dx = int(round(-0.2 * (y - 15)))
            white[y, 25 + dx:80 + dx] = True
        idx = np.where(white, 1, 0).astype(np.int16)

        model = drawing._bust_geometry(white, self.body(2), idx,
                                       self.materials)

        self.assertLess(model["sway_deg"], -5.0)
        left, right = model["lobes"]
        self.assertLess(left[1], right[1] - 2.0)

    def test_face_midline_anchors_lobes(self):
        materials = _cloth_materials() + [
            {"id": "skin", "role": "skin", "refs": ["#f0d0b0"]}]
        idx = self.idx.copy()
        idx[5:15, 60:66] = 2

        model = drawing._bust_geometry(
            self.white, self.body(2), idx, materials)

        self.assertEqual(model["center_source"], "face")
        self.assertAlmostEqual(model["center_x"], 62.5, places=1)

    def test_head_axis_is_measured_above_the_shoulders(self):
        materials = _cloth_materials() + [
            {"id": "skin", "role": "skin", "refs": ["#f0d0b0"]}]
        idx = self.idx.copy()
        idx[5:15, 58:68] = 2

        model = drawing._bust_geometry(self.white, self.body(2), idx, materials)

        self.assertAlmostEqual(model["head_x"], 62.5, places=1)
        self.assertAlmostEqual(model["head_top"], 5.0, places=1)
        self.assertEqual(model["shoulder_y"], 15.0)

    def test_seam_guide_is_clipped_to_blouse_rows(self):
        mask = np.zeros((30, 30), dtype=bool)
        mask[10:20, 5:25] = True

        clipped = drawing._clip_seam_rows(
            [(5, 3.0), (12, 3.0), (15, 30.0)], mask)

        self.assertEqual(len(clipped), 2)
        for y, x in clipped:
            row = np.flatnonzero(mask[y])
            self.assertGreaterEqual(x, row.min())
            self.assertLessEqual(x, row.max())

    def test_body_guide_is_measured_before_shading(self):
        layers = drawing.build_cloth_layers(
            self.rgb, self.fg, self.idx, self.materials,
            body=self.body(3))

        model = layers.stats["body"]
        self.assertEqual(model["mask_id"], 1)
        self.assertTrue(model["lobes"])
        self.assertGreater(layers.form.sum(), 0)


class FormFieldContinuityTests(unittest.TestCase):
    """Volume shading must be one field over the whole garment silhouette."""

    def test_material_break_does_not_restart_the_cylinder_field(self):
        # v10.2 ③: the blouse hem cuts the skirt into short runs; measuring
        # each material separately restarted the cylinder and left a bright
        # beige wedge right under the hem.
        shape = (80, 80)
        idx = np.full(shape, -1, dtype=np.int16)
        idx[40:76, 10:70] = 2          # skirt
        idx[5:40, 10:70] = 1           # blouse body
        idx[40:46, 32:48] = 1          # blouse hem tip over the skirt
        fg = idx >= 0
        rgb = np.zeros(shape + (3,), dtype=np.uint8)
        rgb[idx == 1] = (255, 255, 255)
        rgb[idx == 2] = (203, 184, 159)
        materials = [
            {"id": "blouse", "role": "white",
             "refs": ["#ffffff", "#adbca9", "#6d7b65"]},
            {"id": "skirt", "role": "cloth", "group": "skirt",
             "refs": ["#cbb89f", "#a8957d", "#6e5f52"]},
        ]

        layers = drawing.build_cloth_layers(rgb, fg, idx, materials)

        self.assertLessEqual(
            layers.stats["form_field_break"], 0.05,
            "the field must stay continuous across a material boundary")


class HeadCastTests(unittest.TestCase):
    """The head is the only occluder above the shoulders, and its projection
    must land on the back-lit half of the torso."""

    def setUp(self):
        shape = (130, 140)
        self.fg = np.ones(shape, dtype=bool)
        self.rgb = np.full(shape + (3,), (255, 255, 255), dtype=np.uint8)
        self.materials = [
            {"id": "hair", "role": "hair",
             "refs": ["#ffffff", "#f7b8a8", "#e07a8a"]},
            {"id": "blouse", "role": "white",
             "refs": ["#ffffff", "#adbca9", "#6d7b65"]},
            {"id": "skin", "role": "skin",
             "refs": ["#ffddcc", "#d99a7e"]},
        ]
        idx = np.zeros(shape, dtype=np.int16)
        idx[5:60, 35:95] = 0           # hair mass above the shoulder line
        idx[10:45, 50:80] = 2          # face
        idx[60:120, 25:105] = 1        # blouse torso
        idx[65:120, 30:38] = 0         # long lock hanging on the lit side
        self.idx = idx
        self.body = {"bust": {"size": 2, "separation": 0.45},
                     "torso": {"lean": 0.0}}

    def _build(self):
        return drawing.build_cloth_layers(
            self.rgb, self.fg, self.idx, self.materials, body=self.body)

    def test_no_projection_on_the_lit_side(self):
        layers = self._build()
        model = layers.stats["body"]
        yy, xx = np.mgrid[0:self.idx.shape[0], 0:self.idx.shape[1]]

        occl = layers.occlusion
        self.assertTrue(occl.any(), "head shadow should still be projected")
        self.assertFalse((occl & (xx < model["center_x"])).any(),
                         "hair must not paint a band on the lit side")
        self.assertFalse(occl[:, :45].any(),
                         "a hanging lock on the lit side must not cast")

    def test_shadow_is_below_the_shoulders_on_the_back_lit_half(self):
        layers = self._build()
        model = layers.stats["body"]
        rows = np.nonzero(layers.occlusion)[0]
        cols = np.nonzero(layers.occlusion)[1]
        self.assertGreaterEqual(rows.min(), model["shoulder_y"] - 1.0)
        self.assertGreaterEqual(cols.min(), model["center_x"] - 0.5)

        head = drawing._head_occluder(self.idx, self.materials, model)
        self.assertIsNotNone(head)
        width = float(cols.max() - cols.min() + 1)
        head_width = float(np.nonzero(head)[1].max()
                           - np.nonzero(head)[1].min() + 1)
        self.assertGreaterEqual(width, 0.5 * head_width)
        self.assertLessEqual(width, 2.0 * head_width)

    def test_contact_band_touches_the_occluder_without_a_white_gap(self):
        layers = self._build()
        model = layers.stats["body"]
        head = drawing._head_occluder(self.idx, self.materials, model)
        distance = distance_transform_edt(~head)
        self.assertEqual(float(distance[layers.occlusion].min()), 1.0,
                         "shadow must start on the pixel adjacent to the head")
        tones = layers.tones["occlusion"]
        self.assertEqual(int(tones[layers.occlusion].max()), 2,
                         "the 1px contact band must use the deep tone")


class PromptParameterTests(unittest.TestCase):
    def test_style_no_longer_hardcodes_body_shape(self):
        self.assertNotIn("6-head proportions", prompt.STYLE_POS)
        self.assertNotIn("narrow shoulders", prompt.STYLE_POS)

    def test_prompt_uses_effective_body_tokens(self):
        spec = {
            "gender": "female",
            "proportions": {"heads": 6.5},
            "body": {"heads": 6.5, "shoulder_ratio": 1.4,
                     "face_width_ratio": 0.64,
                     "bust": {"size": 3}},
            "hair": {"length": "bob", "color": "brown",
                     "bangs": "side_part", "reflection": "ring"},
            "face": {"eyes": "almond", "brows": "thin_flat",
                     "nose": "dot", "mouth": "straight"},
            "outfit": {"type": "sailor", "base": "white blouse",
                       "collar": "sailor collar", "accent": "blue scarf",
                       "bottom": "navy skirt"},
            "render": {"tier": "half", "expression": "neutral"},
        }
        positive, _ = prompt.build(spec)
        self.assertIn("6.5 head", positive)
        self.assertIn("shoulder width 1.40 head heights", positive)
        self.assertIn("visible bust volume", positive)

    def test_existing_specs_build_with_defaults(self):
        for rel in ("characters/momo/spec.json",
                    "characters/akira/spec.json",
                    "characters/girl_v2/spec.json"):
            spec = schema.load(ROOT / rel)
            positive, negative = prompt.build(spec)
            self.assertIn("PC-98", positive)
            self.assertIn("modern anime", negative)


if __name__ == "__main__":
    unittest.main()
