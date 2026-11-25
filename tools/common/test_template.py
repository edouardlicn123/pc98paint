# -*- coding: utf-8 -*-
"""三层模板与 schema 扩展的回归测试（原型/变体/合并/自动选择/非法配置）。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "common"))

import schema  # noqa: E402
import template  # noqa: E402


class TemplateDataTests(unittest.TestCase):
    def test_real_templates_match_index_counts_and_cross_refs(self):
        index = schema.validate_index(template.load_index())
        self.assertEqual(len(index["archetypes"]), 25)
        self.assertGreaterEqual(len(index["outfits"]), 25)
        arch_files = sorted((ROOT / "characters" / "templates" / "archetypes")
                            .glob("*.json"))
        outfit_files = sorted((ROOT / "characters" / "templates" / "outfits")
                              .glob("*.json"))
        self.assertEqual(len(arch_files), 25)
        self.assertGreaterEqual(len(outfit_files), 25)
        for path in arch_files + outfit_files:
            schema.load_template(path)
        arch_ids = {item["id"] for item in index["archetypes"]}
        for item in index["outfits"]:
            self.assertIn(item["archetype"], arch_ids)

    def test_existing_specs_still_load(self):
        for rel in ("characters/momo/spec.json",
                    "characters/akira/spec.json",
                    "characters/girl_v2/spec.json"):
            spec = schema.load(ROOT / rel)
            self.assertIn("proportions", spec)

    def test_loli_reference_corrections(self):
        """02 萝莉复核：胸部非平、长发双马尾、青绿瞳、黄滚边、雀斑。"""
        arch = template.load_archetype("loli")
        self.assertEqual(arch["body"]["bust"]["size"], 2)
        self.assertEqual(arch["hair"]["length"], "long")
        self.assertIn("freckles", arch["face"]["markings"])
        outfit = template.load_outfit("loli_sailor")
        iris = next(item for item in outfit["materials"]
                    if item["id"] == "iris")
        self.assertEqual(iris["refs"][0], "#338888")
        self.assertTrue(any(item["role"] == "accent"
                            for item in outfit["materials"]))

    def test_template_render_config_overrides_instance(self):
        """新管线：materials/drawing 以模板为准，实例旧配置不得绕过。"""
        spec = {
            "id": "override",
            "materials": [{"id": "legacy", "role": "white", "refs": ["#ffffff"]}],
            "drawing": {"folds": []},
            "template": {"archetype": "loli", "outfit": "loli_sailor"},
        }
        effective, _ = template.resolve_template(spec)
        outfit = template.load_outfit("loli_sailor")
        self.assertEqual(effective["materials"], outfit["materials"])
        self.assertEqual(effective["drawing"], outfit["drawing"])

    def test_all_active_tools_are_registered_in_agents(self):
        """工具/文档登记纪律的可执行守卫：新增脚本未登记即红。"""
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        missing = []
        for path in sorted((ROOT / "tools").rglob("*.py")):
            if "legacy" in path.parts:
                continue
            rel = path.relative_to(ROOT).as_posix()
            if rel not in agents:
                missing.append(rel)
        self.assertEqual(missing, [], f"AGENTS.md 未登记: {missing}")
        missing_docs = [path.name for path in sorted((ROOT / "docs").glob("*.md"))
                        if path.name not in agents]
        self.assertEqual(missing_docs, [],
                         f"AGENTS.md 未登记文档: {missing_docs}")


class TemplateValidationTests(unittest.TestCase):
    def setUp(self):
        self.materials = [
            {"id": "coat", "role": "cloth", "refs": ["#998877", "#666655"]},
            {"id": "blouse", "role": "white",
             "refs": ["#ffffff", "#ddddbb"]},
        ]

    def test_unknown_template_reference_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "不存在"):
            schema.validate_template_ref({"archetype": "no_such_archetype"})

    def test_bust_size_out_of_range_is_rejected(self):
        body = {"heads": 6.5, "shoulder_ratio": 1.2,
                "bust": {"size": 5}}
        with self.assertRaisesRegex(ValueError, "bust.size"):
            schema.validate_body(body)

    def test_garment_layer_references_unknown_material(self):
        layers = [{"id": "skirt", "over": ["skin"]}]
        with self.assertRaisesRegex(ValueError, "未知材质"):
            schema.validate_garment_layers(layers, self.materials)

    def test_occlusion_cannot_have_path_and_derive(self):
        config = {"occlusions": [{
            "over": "coat", "under": "blouse", "width": 2,
            "path": [[0.2, 0.2], [0.8, 0.2]], "derive": "layer_edge",
        }]}
        with self.assertRaisesRegex(ValueError, "同时"):
            schema.validate_drawing(config, self.materials)

    def test_unknown_derive_mode_is_rejected(self):
        config = {"occlusions": [{
            "over": "coat", "under": "blouse", "derive": "magic", "width": 2,
        }]}
        with self.assertRaisesRegex(ValueError, "derive"):
            schema.validate_drawing(config, self.materials)


class ResolveTemplateTests(unittest.TestCase):
    def test_instance_fields_win_and_template_fills_missing(self):
        spec = {
            "id": "merge_case", "name": "合并测试", "gender": "female",
            "proportions": {"heads": 7.0},
            "outfit": {"type": "sailor"},
            "template": {"archetype": "female_highschool_4",
                         "outfit": "female_highschool_4_sailor"},
        }
        effective, meta = template.resolve_template(spec)
        self.assertEqual(effective["proportions"]["heads"], 7.0)
        self.assertEqual(effective["body"]["bust"]["size"], 2)
        self.assertEqual(meta["resolved_template"]["archetype"],
                         "female_highschool_4")
        self.assertEqual(meta["resolved_template"]["source"], "explicit")

    def test_auto_selection_is_deterministic_for_three_key_sets(self):
        cases = [
            ({"gender": "female", "outfit": {"type": "sailor"},
              "proportions": {"heads": 6.2}}, "female_highschool_4"),
            ({"gender": "male", "outfit": {"type": "gakuran"},
              "proportions": {"heads": 7.0}}, "male_highschool_1"),
            ({"gender": "female", "outfit": {"type": "suit"},
              "proportions": {"heads": 7.0}}, "mature_woman_1"),
        ]
        for spec, expected in cases:
            first = template.resolve_template(dict(spec))[1]
            second = template.resolve_template(dict(spec))[1]
            self.assertEqual(first["resolved_template"]["archetype"], expected)
            self.assertEqual(first["resolved_template"]["source"], "auto")
            self.assertEqual(first, second)

    def test_fixture_archetype_can_mount_two_outfits(self):
        fixtures = ROOT / "tools" / "tachie" / "test_fixtures" / "templates"
        base = {"id": "fixture_case", "name": "测试原型", "gender": "female",
                "proportions": {"heads": 6.5},
                "outfit": {"type": "casual"}}
        auto = template.resolve_template(dict(base), templates_dir=fixtures)[1]
        self.assertEqual(auto["resolved_template"]["outfit"], "fixture_casual")

        explicit = dict(base)
        explicit["template"] = {"archetype": "fixture_female",
                                "outfit": "fixture_sailor"}
        sailor, _ = template.resolve_template(explicit, templates_dir=fixtures)
        explicit["template"]["outfit"] = "fixture_casual"
        casual, _ = template.resolve_template(explicit, templates_dir=fixtures)
        sailor_ids = {layer["id"] for layer in sailor["garment_layers"]}
        casual_ids = {layer["id"] for layer in casual["garment_layers"]}
        self.assertIn("blouse", sailor_ids)
        self.assertIn("cardigan", casual_ids)
        self.assertNotEqual(sailor_ids, casual_ids)


if __name__ == "__main__":
    unittest.main()
