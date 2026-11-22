# -*- coding: utf-8 -*-
"""角色管线：Spec → 提示词 → 像素化 → Lint → 资产。

用法：
    python tools/tachie/pipeline.py --spec characters/akira/spec.json \
        --source _work/pc98_src/girl_full_hi.jpg --out akira
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "output"          # 产出统一写 output/（见 AGENTS.md）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import lint  # noqa: E402
import pixelize  # noqa: E402
import prompt  # noqa: E402
import repair  # noqa: E402
import schema  # noqa: E402


def save_drawing_debug(debug, directory):
    """把三类线稿、五类布料和材质归属写入 scratch，不触碰正式图。"""
    directory.mkdir(parents=True, exist_ok=True)
    fills = debug["fills"]
    scale = 3

    def save(name, image):
        image.resize((image.width * scale, image.height * scale),
                     Image.Resampling.NEAREST).save(directory / name)

    line_colors = {1: (30, 30, 30), 2: (51, 136, 204), 3: (238, 102, 153)}
    out = fills.copy()
    for kind, color in line_colors.items():
        out[debug["line_kind"] == kind] = color
    save("line_layers.png", Image.fromarray(out))

    layer_colors = {"base": (187, 187, 187), "form": (68, 102, 187),
                    "fold": (238, 136, 51), "occlusion": (136, 68, 153),
                    "highlight": (255, 238, 102)}
    for name, color in layer_colors.items():
        out = fills.copy()
        out[debug["cloth_layers"][name]] = color
        save(f"cloth_{name}.png", Image.fromarray(out))

    idx = debug["material_idx"]
    colors = np.array([(34, 34, 34), (238, 187, 153), (255, 153, 170),
                       (255, 255, 255), (153, 136, 119), (68, 68, 51),
                       (238, 187, 51), (51, 136, 136), (102, 170, 119),
                       (187, 102, 153), (102, 119, 187), (238, 136, 102),
                       (170, 187, 102), (136, 102, 187), (102, 187, 170),
                       (187, 153, 102), (153, 153, 153)], dtype=np.uint8)
    mapped = np.zeros(idx.shape, dtype=np.int16)
    valid = idx >= 0
    mapped[valid] = (idx[valid] % (len(colors) - 1)) + 1
    save("material_idx.png", Image.fromarray(colors[mapped]))
    report = {
        "sprite_box": debug["sprite_box"],
        "drawing": debug.get("drawing_report", {}),
        "line": {
            "outline": int((debug["line_kind"] == 1).sum()),
            "structure": int((debug["line_kind"] == 2).sum()),
            "strands": int((debug["line_kind"] == 3).sum()),
            "protected": int(debug["line_protected"].sum()),
            "ink_core": int(debug["ink_core"].sum()),
            "contrast_edge": int(debug["contrast_edge"].sum()),
        },
    }
    (directory / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--palette", default="", help="16 色色板 JSON；给出则走材质区域渲染")
    ap.add_argument("--tier", default="", choices=("", "closeup", "half", "full"))
    ap.add_argument("--legacy-render", action="store_true",
                    help="强制旧路线 pixelize + repair（默认在给出 --palette 时走材质区域）")
    ap.add_argument("--drawing-debug", action="store_true",
                    help="在 _work/scratch 输出线稿/布料分层诊断")
    args = ap.parse_args()

    spec = schema.load(ROOT / args.spec)
    pos, neg = prompt.build(spec)
    print("PROMPT:", pos)
    print("NEGATIVE:", neg)

    out_prefix = OUT_DIR / Path(args.out).name   # 一律落到 output/ 下
    tier = args.tier or spec["render"].get("tier", "half")
    stats = {}
    material_report = None
    if args.palette and not args.legacy_render:
        import asset3
        import palette98
        pal = palette98.load(args.palette)
        name = f"{out_prefix.name}_{tier}"
        baseline = spec["checks"].get("material_area", {}).get(tier)
        if baseline:
            expected_source = (ROOT / baseline["source"]).resolve()
            actual_source = (ROOT / args.source).resolve()
            if expected_source != actual_source:
                print("SKIP  material_area: 源图与基线不一致")
                baseline = None
        _, render_debug = asset3.render(
            ROOT / args.source, tier, name, pal, material_region=True,
            materials=spec.get("materials"), material_baseline=baseline,
            return_debug=True, drawing_config=spec.get("drawing"))
        if args.drawing_debug:
            save_drawing_debug(
                render_debug,
                ROOT / "_work" / "scratch" / f"{out_prefix.name}_drawing")
        material_report = render_debug["material_report"]
        canvas = Image.open(OUT_DIR / f"{name}.png").convert("RGBA")
        a = np.array(canvas)
        ys, xs = np.where(a[..., 3] > 0)
        img = canvas.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
        stats = {
            "renderer": "matregion", "tier": tier,
            "materials": material_report["stats"] if material_report else {},
            "material_area_baseline": baseline["source"] if baseline else None,
        }
    else:
        img, stats = pixelize.pixelize(ROOT / args.source, spec["render"], out_prefix)
        for _ in range(2):
            report = lint.lint(img, spec)
            if report["pass"]:
                break
            img = repair.repair(img, spec)
        img = repair.palette_lock(img, spec)
        img = repair.eyebrow_fix(img, spec)
        img = repair.drop_specks(img)

    report = lint.lint(img, spec)
    if material_report:
        report["checks"].update(material_report["checks"])
        report["materials"] = material_report
        report["pass"] = report["pass"] and material_report["pass"]
    img.save(Path(str(out_prefix) + "_tachie.png"))
    report["render_stats"] = stats
    out_json = Path(str(out_prefix) + "_lint.json")
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    for name, item in report["checks"].items():
        print(f"{'PASS' if item['pass'] else 'FAIL'}  {name}: {item['value']}  (limit {item.get('limit')})")
    print("RESULT:", "PASS" if report["pass"] else "FAIL")


if __name__ == "__main__":
    main()
