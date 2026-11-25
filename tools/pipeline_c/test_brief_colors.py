# -*- coding: utf-8 -*-
"""Unit smoke tests for brief color overrides (pipeline C, step C3)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.pipeline_c import brief  # noqa: E402

# Deterministic pick for female / teen / sailor (ref "18" precedes "25").
SELECTED = "female_highschool_4"


def _brief(colors):
    return {
        "gender": "female",
        "age_group": "teen",
        "outfit_type": "sailor",
        "name": "pipeline c test",
        "slug": "pipeline_c_test",
        "colors": colors,
    }


class BriefColorTest(unittest.TestCase):
    def test_single_color_derives_three_tones_and_keeps_role(self):
        effective, meta = brief.resolve(
            _brief({"top": ["#3355aa"], "accent": ["#cc3344"]}))
        self.assertEqual(meta["auto_select"]["archetype"], SELECTED)
        materials = {item["id"]: item for item in effective["materials"]}
        for material_id, role in (("top", "white"), ("accent", "accent")):
            self.assertEqual(len(materials[material_id]["refs"]), 3)
            self.assertEqual(materials[material_id]["role"], role)
            self.assertIn("paint", materials[material_id])
        self.assertEqual(sorted(meta["colors"]["derived"]), ["accent", "top"])

    def test_three_colors_are_used_verbatim(self):
        refs = ["#112233", "#445566", "#778899"]
        effective, meta = brief.resolve(_brief({"bottom": refs}))
        materials = {item["id"]: item for item in effective["materials"]}
        self.assertEqual(materials["bottom"]["refs"], refs)
        self.assertEqual(materials["bottom"]["role"], "cloth")
        self.assertEqual(meta["colors"]["derived"], [])

    def test_untouched_and_unknown_materials(self):
        template_materials = {
            item["id"]: item for item in brief.resolve(_brief({}))[0]["materials"]}
        effective, meta = brief.resolve(_brief({"shoes": ["#000000"]}))
        materials = {item["id"]: item for item in effective["materials"]}
        self.assertIn("shoes", meta["colors"]["ignored"])
        self.assertEqual(materials["hair"]["refs"],
                         template_materials["hair"]["refs"])
        self.assertEqual(materials["top"]["refs"],
                         template_materials["top"]["refs"])


if __name__ == "__main__":
    unittest.main()
