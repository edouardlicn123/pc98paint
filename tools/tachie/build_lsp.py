# -*- coding: utf-8 -*-
"""Build layered sprite projects (LSP) stage by stage.

v1 implements the project contract plus the *structure* stage (torso frame,
bust lobes and four limbs).  Later stages (base/detail/shade/highlight/lineart)
reuse the same ledger and will be added after the structure is approved.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import binary_fill_holes, label

ROOT = Path(__file__).resolve().parents[2]
TACHIE = Path(__file__).resolve().parent
LIB = Path(__file__).resolve().parents[1] / "lib"
COMMON = Path(__file__).resolve().parents[1] / "common"
for p in (TACHIE, LIB, COMMON):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import lsp  # noqa: E402
import limbs  # noqa: E402
import lineart  # noqa: E402
import matregion  # noqa: E402
import schema as _schema  # noqa: E402
import template as _tmpl  # noqa: E402
import drawing  # noqa: E402
from bust_sample2 import background_mask  # noqa: E402

DETECT_H = 720
SUPPORTED = ("structure", "lineart")


def _rel(path) -> str:
    p = Path(path).resolve()
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def _abs(path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (ROOT / p)


def _foreground(src: Image.Image) -> np.ndarray:
    fg = ~background_mask(src)
    lab, n = label(fg, structure=np.ones((3, 3), bool))
    if n > 1:
        sizes = np.bincount(lab.ravel())
        sizes[0] = 0
        fg = lab == int(sizes.argmax())
    return binary_fill_holes(fg)


def _crop_box(fg: np.ndarray):
    ys, xs = np.where(fg)
    if not len(ys):
        raise SystemExit("源图没有前景")
    h, w = fg.shape
    pad = max(4, int(round(min(h, w) * 0.01)))
    x0, x1 = max(0, xs.min() - pad), min(w, xs.max() + 1 + pad)
    y0, y1 = max(0, ys.min() - pad), min(h, ys.max() + 1 + pad)
    return int(x0), int(y0), int(x1), int(y1)


def _load_spec(scene: dict):
    spec = _schema.load(_abs(scene["spec"]))
    effective, _ = _tmpl.resolve_template(spec)
    return spec, effective


def _layer_entries() -> list:
    return [
        {"id": "base", "file": "layers/00_base.png", "role": "base",
         "blend": "normal", "opacity": 1.0, "locked": True},
        {"id": "detail", "file": "layers/05_detail.png", "role": "detail",
         "blend": "normal", "opacity": 1.0},
        {"id": "shade", "file": "layers/10_shade.png", "role": "shade",
         "blend": "multiply", "opacity": 0.85, "clip": True},
        {"id": "highlight", "file": "layers/20_highlight.png", "role": "highlight",
         "blend": "screen", "opacity": 0.90, "clip": True},
        {"id": "lineart", "file": "layers/30_lineart.png", "role": "lineart",
         "blend": "normal", "opacity": 1.0},
        {"id": "structure", "file": "layers/90_structure.png", "role": "structure",
         "blend": "normal", "visible": False, "export": False},
        {"id": "material", "file": "layers/95_material.png", "role": "mask",
         "encoding": "index8", "export": False},
    ]


def cmd_init(args) -> int:
    spec_path = _abs(args.spec)
    source_path = _abs(args.source)
    if not spec_path.is_file():
        raise SystemExit(f"spec 不存在: {spec_path}")
    if not source_path.is_file():
        raise SystemExit(f"源图不存在: {source_path}")
    spec = _schema.load(spec_path)
    effective, _ = _tmpl.resolve_template(spec)
    name = args.name or spec.get("id") or spec_path.parent.name

    src = Image.open(source_path).convert("RGB")
    fg = _foreground(src)
    x0, y0, x1, y1 = _crop_box(fg)
    width, height = x1 - x0, y1 - y0

    out = _abs(args.out)
    (out / "layers").mkdir(parents=True, exist_ok=True)
    palette = _abs(args.palette) if args.palette else spec_path.parent / "palette.json"
    scene = {
        "format": lsp.FORMAT,
        "profile": lsp.PROFILE,
        "character": name,
        "tier": args.tier,
        "spec": _rel(spec_path),
        "source": _rel(source_path),
        "canvas": {"width": width, "height": height},
        "unit": round(height / 360.0, 6),
        "target": {"canvas": [640, 400], "figure_h": 360, "margin_y": 20},
        "palette": _rel(palette),
        "palette_groups": "palette_groups.json",
        "materials": "materials.json",
        "structure": "structure.json",
        "layers": _layer_entries(),
    }
    lsp.save_scene(out, scene)
    materials = [
        {"id": m["id"], "role": m.get("role"), "refs": m.get("refs", [])}
        for m in effective.get("materials", [])
    ]
    (out / "materials.json").write_text(
        json.dumps({"background": 0, "materials": materials},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lsp.save_stages(out, {"order": list(lsp.STAGE_ORDER), "stages": {}})
    print(f"init -> {out}")
    print(f"  canvas {width}x{height}  unit={scene['unit']:.3f}  tier={args.tier}")
    print(f"  source crop x{x0} y{y0} -> x{x1} y{y1}")
    return 0


def _detect_scale(scene: dict, detect_h: int):
    width = int(scene["canvas"]["width"])
    height = int(scene["canvas"]["height"])
    dh = min(detect_h, height)
    dw = max(1, int(round(width * dh / height)))
    return dw, dh, height / float(dh)


def _fallback_guide(height: int, width: int) -> dict:
    return {
        "size": 0, "lobes": [], "mask_id": None,
        "shoulder_y": height * 0.35, "waist_y": height * 0.72,
        "center_x": width / 2.0, "center_y": height * 0.55,
        "torso_left": width * 0.26, "torso_right": width * 0.74,
        "torso_width": width * 0.48, "sway_deg": 0.0,
        "head_x": width / 2.0, "head_top": height * 0.02,
    }


def _tilted_line(guide: dict, y: float, band=None) -> list:
    """Anatomical cross-section perpendicular to the measured sway axis."""
    slope = float(guide.get("slope") or 0.0)
    cx = limbs._axis_x(guide, y)
    if band is not None:
        xs = [float(band[0]), float(band[1])]
    else:
        xs = []
        for key, fallback in (("seam_left", guide["torso_left"]),
                              ("seam_right", guide["torso_right"])):
            pts = guide.get(key) or []
            if pts:
                ys = [p[0] for p in pts]
                xs.append(float(np.interp(y, ys, [p[1] for p in pts])))
            else:
                xs.append(float(fallback))
    return [[x, y - slope * (x - cx)] for x in xs]


def _seams(guide: dict):
    """Traced body/arm seams when available, else the sway-aligned side lines."""
    sl = _tilted_line(guide, guide["shoulder_y"])
    wl = _tilted_line(guide, guide["waist_y"])
    out = {}
    for i, (side, key) in enumerate((("left", "seam_left"), ("right", "seam_right"))):
        pts = guide.get(key) or []
        out[side] = [[float(x), float(y)] for y, x in pts] if pts \
            else [sl[i], wl[i]]
    return out


def _largest_component(mask: np.ndarray) -> np.ndarray:
    lab, n = label(mask)
    if not n:
        return np.zeros_like(mask, dtype=bool)
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    return lab == int(sizes.argmax())


def _band_extents(mask: np.ndarray, y: float, half: int = 4):
    """Robust horizontal extent in a small band around an anatomical row."""
    y0 = max(0, int(round(y)) - half)
    y1 = min(mask.shape[0], int(round(y)) + half + 1)
    _, xs = np.where(mask[y0:y1])
    if xs.size < 12:
        return None
    return [float(np.percentile(xs, 5)), float(np.percentile(xs, 95))]


def _measure_head(skin_mask: np.ndarray, guide: dict) -> None:
    """Measure the face centre and chin separately from the neck."""
    top = int(guide.get("head_top") or 0)
    shoulder = int(guide["shoulder_y"])
    limit = min(skin_mask.shape[0], shoulder + max(8, (shoulder - top) // 8))
    face = _largest_component(skin_mask[:limit])
    rows = {}
    for y in range(top, limit):
        xs = np.flatnonzero(face[y])
        if xs.size >= 4:
            rows[y] = (int(xs.min()), int(xs.max()))
    if not rows:
        return
    peak_y = max(rows, key=lambda y: rows[y][1] - rows[y][0])
    peak_w = max(1, rows[peak_y][1] - rows[peak_y][0] + 1)
    chin_y = min(limit - 1, int(round(top + 0.98 * (shoulder - top))))
    for y in range(peak_y, limit - 2):
        widths = []
        for yy in range(y, y + 3):
            row = rows.get(yy)
            widths.append(0 if row is None else row[1] - row[0] + 1)
        if all(0 < w < 0.48 * peak_w for w in widths):
            chin_y = y
            break
    wide = [y for y in rows
            if abs(y - peak_y) <= max(3, int(0.04 * skin_mask.shape[0]))
            and rows[y][1] - rows[y][0] + 1 >= 0.82 * peak_w]
    face_x = float(np.median([(rows[y][0] + rows[y][1]) / 2 for y in (wide or [peak_y])]))
    chin_rows = [y for y in range(max(top, chin_y - 2), min(limit, chin_y + 3))
                 if y in rows]
    chin_x = float(np.median([(rows[y][0] + rows[y][1]) / 2 for y in chin_rows]))
    # Project the measured face centre into the nose/mouth band, then extend
    # through the chin and skull top.  Local jaw rows include hair/neck pixels
    # on the turned side, so they must not replace the widest-face centre.
    axis_y = int(round(top + 0.70 * (chin_y - top)))
    axis_tilt = (chin_x - face_x) / max(1.0, chin_y - axis_y)
    axis_top_x = face_x - axis_tilt * (axis_y - top)
    guide["head_axis"] = [[axis_top_x, float(top)], [chin_x, float(chin_y)]]
    guide["head_top_x"] = face_x
    guide["head_chin"] = [chin_x, float(chin_y)]
    guide["head_tilt"] = (chin_x - face_x) / max(1.0, chin_y - top)


def _structure_from_guides(guide: dict, limb_data: dict, detect_h: int) -> dict:
    lobes = []
    for cx, cy, rx, ry in guide.get("lobes", []):
        lobes.append({"cx": float(cx), "cy": float(cy),
                      "rx": float(rx), "ry": float(ry)})
    sy = float(guide["shoulder_y"])
    wy = float(guide["waist_y"])
    lower_wy = float(guide.get("anatomy_waist_y", wy))
    htop = float(guide.get("head_top") or 0.0)
    hx = float(guide.get("head_top_x", guide.get("head_x", guide["center_x"])))
    chin = guide.get("head_chin") or [limbs._axis_x(guide, sy), htop + guide["head_h"]]
    head_h = max(8.0, float(chin[1]) - htop)
    head_ry = 0.5 * head_h
    head_axis = guide.get("head_axis") or [[hx, htop],
                                           [float(chin[0]), float(chin[1])]]
    # The skull arc is the midline's frame: same centre, same lean.  Keeping a
    # separately measured ellipse tilt made the arc drift off the nose/mouth
    # axis on turned faces.
    axis_slope = (float(head_axis[1][0]) - float(head_axis[0][0])) / max(
        1.0, float(head_axis[1][1]) - float(head_axis[0][1]))
    head = {
        "x": hx, "top": htop,
        "cx": 0.5 * (float(head_axis[0][0]) + float(head_axis[1][0])),
        "cy": 0.5 * (float(head_axis[0][1]) + float(head_axis[1][1])),
        "rx": 0.82 * head_ry, "ry": head_ry,
        "tilt": axis_slope,
        "chin": [float(chin[0]), float(chin[1])],
        "axis": head_axis,
    }
    # Waist diameter is a character datum measured in head heights.
    waist_r = 0.5 * guide["head_h"] * guide.get("waist_ratio", 0.50)
    waist_cx = limbs._axis_x(guide, wy)
    waist_line = _tilted_line(guide, wy, [waist_cx - waist_r, waist_cx + waist_r])
    waist = {
        "cx": waist_cx, "cy": wy, "rx": waist_r, "ry": waist_r,
        "tilt": float(guide.get("slope") or 0.0),
    }
    pelvis_len = max(1.0, lower_wy - sy)
    py = float(guide.get("pelvis_y", lower_wy + 0.30 * pelvis_len))
    pelvis_line = _tilted_line(guide, py, guide.get("pelvis_band"))
    pelvis = {
        "cx": (pelvis_line[0][0] + pelvis_line[1][0]) / 2,
        "cy": (pelvis_line[0][1] + pelvis_line[1][1]) / 2,
        "rx": abs(pelvis_line[1][0] - pelvis_line[0][0]) / 2,
        "ry": 0.24 * pelvis_len,
        # The hip line stays level while standing: the pelvis ring must not
        # inherit the torso sway, or the trailing hip socket sinks below the
        # leading one and the thighs read as different lengths.
        "tilt": 0.0,
    }
    return {
        "unit": detect_h / 360.0,
        "head": head,
        "neck": [limbs._axis_x(guide, sy), sy],
        "shoulder_y": sy,
        "waist_y": wy,
        "shoulder_line": [a["shoulder"] for a in limb_data["arms"]],
        "waist_line": waist_line,
        "waist": waist,
        "pelvis": pelvis,
        "torso": {
            "center_x": float(guide["center_x"]),
            "left": float(guide["torso_left"]),
            "right": float(guide["torso_right"]),
            "width": float(guide["torso_width"]),
            "sway_deg": float(guide.get("sway_deg", 0.0)),
            "center_source": guide.get("center_source", "face"),
        },
        "bust": {"size": guide.get("size", 0), "lobes": lobes},
        "seams": _seams(guide),
        "limbs": limb_data,
    }


def build_structure(args) -> int:
    root = lsp.project_root(args.lsp)
    scene = lsp.load_scene(root)
    lsp.validate_scene(root, scene)
    spec, effective = _load_spec(scene)
    source = Image.open(_abs(scene["source"])).convert("RGB")
    fg = _foreground(source)
    x0, y0, x1, y1 = _crop_box(fg)
    width, height = int(scene["canvas"]["width"]), int(scene["canvas"]["height"])
    if (x1 - x0, y1 - y0) != (width, height):
        raise SystemExit(f"源图裁切 {x1 - x0}x{y1 - y0} 与 canvas {width}x{height} 不一致，请重新 init")

    crop = source.crop((x0, y0, x1, y1))
    crop_fg = Image.fromarray((fg[y0:y1, x0:x1] * 255).astype(np.uint8), "L")
    dw, dh, factor = _detect_scale(scene, args.detect_h)
    small = np.asarray(crop.resize((dw, dh), Image.BOX))
    small_fg = np.asarray(crop_fg.resize((dw, dh), Image.NEAREST)) > 127

    materials = effective["materials"]
    idx = matregion.classify_materials(
        small, small_fg, materials, tier=scene.get("tier", "half"),
        scale=dh / 360.0)
    lum = small.astype(np.float32).mean(-1) / 255.0
    guide = drawing.body_guide(idx, materials, effective.get("body") or {}, lum)
    if not guide or guide.get("torso_width") is None:
        guide = _fallback_guide(dh, dw)
    body = effective.get("body") or {}
    guide["shoulder_ratio"] = float(body.get("shoulder_ratio", 1.4))
    guide["waist_ratio"] = float(body.get("waist_ratio", 0.50))

    role_ids = {}
    for i, m in enumerate(materials):
        role_ids.setdefault(m.get("role"), []).append(i)
    body_ids = [i for role in ("skin", "white", "cloth", "accent")
                for i in role_ids.get(role, [])]
    body_mask = np.isin(idx, body_ids)
    skin_mask = np.isin(idx, role_ids.get("skin", []))
    _measure_head(skin_mask, guide)

    # Keep the bust guide's waist for the abdominal circle.  Only the pelvis
    # uses the top and cross-section of the large lower-garment component.
    lower = None
    lower_top = None
    lower_area = 0
    cloth_ids = [i for role in ("cloth",) for i in role_ids.get(role, [])]
    cloth_lab, cloth_n = label(np.isin(idx, cloth_ids))
    for component_id in range(1, cloth_n + 1):
        component = cloth_lab == component_id
        ys = np.nonzero(component)[0]
        if not ys.size or float(ys.min()) <= guide["waist_y"]:
            continue
        area = int(ys.size)
        if area > lower_area:
            lower, lower_top, lower_area = component, float(ys.min()), area
    wy = lower_top if lower_top is not None else float(guide["waist_y"])
    guide["anatomy_waist_y"] = wy
    py = wy + 0.30 * max(1.0, wy - guide["shoulder_y"])
    guide["pelvis_y"] = py
    pelvis_band = _band_extents(lower, py) if lower is not None else None
    guide["pelvis_band"] = pelvis_band or [
        limbs._axis_x(guide, py) - 0.60 * guide["torso_width"],
        limbs._axis_x(guide, py) + 0.60 * guide["torso_width"]]

    limbs.apply_proportions(
        guide, effective.get("proportions") or spec.get("proportions"))
    limb_data = limbs.derive_limbs(body_mask, skin_mask, guide)

    structure = limbs.scale_structure(
        _structure_from_guides(guide, limb_data, dh), factor)
    structure["unit"] = round(height / 360.0, 6)

    out_dir = root
    (out_dir / "structure.json").write_text(
        json.dumps(structure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    layer = limbs.render_structure(structure, width, height, structure["unit"])
    entry = next(e for e in scene["layers"] if e["id"] == "structure")
    layer_path = lsp.layer_path(root, entry)
    layer_path.parent.mkdir(parents=True, exist_ok=True)
    layer.save(layer_path)

    check = ROOT / "output" / f"{scene['character']}_{scene['tier']}_structure_check.png"
    check.parent.mkdir(parents=True, exist_ok=True)
    limbs.write_check_image(crop, structure, check, max_h=900)

    st = lsp.record_stage(root, "structure", scene)
    arms = structure["limbs"]["arms"]
    legs = structure["limbs"]["legs"]
    print(f"structure -> {layer_path}")
    print(f"  check  -> {check}")
    print(f"  arms={len(arms)} legs={len(legs)}  "
          f"partial={sum(bool(a['partial']) for a in arms) + sum(bool(l['partial']) for l in legs)}")
    print(f"  stage  -> {st['status']} {st['sha256'][:12]}")
    return 0


def _palette_ink(scene: dict):
    """Darkest neutral ink slot from the character palette."""
    path = scene.get("palette")
    if not path:
        return (74, 63, 54)
    data = json.loads(_abs(path).read_text(encoding="utf-8"))
    colours = [tuple(int(v) for v in c[:3]) for c in data.get("colors", [])
               if len(c) >= 3]
    colours = [c for c in colours if sum(c) > 60]
    if not colours:
        return (74, 63, 54)
    return min(colours, key=lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2])


def _lower_garment_top(mask: np.ndarray, waist_row: int, scale: float) -> float:
    row = int(max(0, waist_row))
    lower = np.zeros_like(mask)
    lower[row:, :] = mask[row:, :]
    lab, n = label(lower)
    best, best_y = 0, None
    for i in range(1, n + 1):
        ys = np.nonzero(lab == i)[0]
        if ys.size > best:
            best, best_y = int(ys.size), float(ys.min())
    return best_y * scale if best_y is not None else -1.0


def build_lineart(args) -> int:
    root = lsp.project_root(args.lsp)
    scene = lsp.load_scene(root)
    lsp.validate_scene(root, scene)
    spec, effective = _load_spec(scene)
    structure_path = root / "structure.json"
    if not structure_path.exists():
        raise SystemExit("lineart 需要 structure.json，请先 build --only structure")
    structure = json.loads(structure_path.read_text(encoding="utf-8"))

    source = Image.open(_abs(scene["source"])).convert("RGB")
    fg = _foreground(source)
    x0, y0, x1, y1 = _crop_box(fg)
    width, height = int(scene["canvas"]["width"]), int(scene["canvas"]["height"])
    if (x1 - x0, y1 - y0) != (width, height):
        raise SystemExit(f"源图裁切 {x1 - x0}x{y1 - y0} 与 canvas {width}x{height} 不一致，请重新 init")
    crop = source.crop((x0, y0, x1, y1))
    crop_fg = Image.fromarray((fg[y0:y1, x0:x1] * 255).astype(np.uint8), "L")
    dw, dh, factor = _detect_scale(scene, args.detect_h)
    small = np.asarray(crop.resize((dw, dh), Image.BOX))
    small_fg = np.asarray(crop_fg.resize((dw, dh), Image.NEAREST)) > 127

    materials = effective["materials"]
    idx = matregion.classify_materials(
        small, small_fg, materials, tier=scene.get("tier", "half"),
        scale=dh / 360.0)
    masks = lineart.role_masks(idx, materials)

    waist_y = float(structure.get("waist_y", 0.0))
    cloth = masks.get("cloth")
    skirt_top = _lower_garment_top(cloth, waist_y / factor, factor) \
        if cloth is not None and cloth.any() else waist_y
    if skirt_top < 0:
        skirt_top = waist_y

    features = {
        "body": effective.get("body") or {},
        "face": effective.get("face") or {},
        "hair": effective.get("hair") or {},
        "outfit": effective.get("outfit") or {},
    }
    layer = lineart.render_lineart(
        structure, masks, features, width, height,
        float(structure.get("unit", scene["unit"])), factor, skirt_top,
        ink=_palette_ink(scene))

    entry = next(e for e in scene["layers"] if e["id"] == "lineart")
    layer_path = lsp.layer_path(root, entry)
    layer_path.parent.mkdir(parents=True, exist_ok=True)
    layer.save(layer_path)

    check = ROOT / "output" / f"{scene['character']}_{scene['tier']}_lineart_check.png"
    check.parent.mkdir(parents=True, exist_ok=True)
    lineart.write_check(crop, layer, check)
    overlay = ROOT / "output" / f"{scene['character']}_{scene['tier']}_lineart_overlay.png"
    lineart.write_overlay(crop, layer, overlay)

    st = lsp.record_stage(root, "lineart", scene)
    print(f"lineart -> {layer_path}")
    print(f"  check   -> {check}")
    print(f"  overlay -> {overlay}")
    print(f"  skirt_top={skirt_top:.1f} ink={_palette_ink(scene)}")
    print(f"  stage   -> {st['status']} {st['sha256'][:12]}")
    return 0


def cmd_build(args) -> int:
    only = args.only
    if only not in SUPPORTED:
        raise SystemExit(f"暂未实现图层: {only}（当前支持: {', '.join(SUPPORTED)}）")
    if only == "structure":
        return build_structure(args)
    if only == "lineart":
        return build_lineart(args)
    return 1


def cmd_preview(args) -> int:
    root = lsp.project_root(args.lsp)
    scene = lsp.load_scene(root)
    if args.layer != "structure":
        raise SystemExit(f"暂未实现预览: {args.layer}")
    structure = json.loads((root / "structure.json").read_text(encoding="utf-8"))
    source = Image.open(_abs(scene["source"])).convert("RGB")
    fg = _foreground(source)
    x0, y0, x1, y1 = _crop_box(fg)
    check = ROOT / "output" / f"{scene['character']}_{scene['tier']}_structure_check.png"
    limbs.write_check_image(source.crop((x0, y0, x1, y1)), structure, check, max_h=900)
    print(f"preview -> {check}")
    return 0


def cmd_confirm(args) -> int:
    root = lsp.project_root(args.lsp)
    st = lsp.confirm_stage(root, args.layer)
    print(f"confirmed {args.layer}: {st['sha256'][:12]}")
    return 0


def cmd_status(args) -> int:
    root = lsp.project_root(args.lsp)
    scene = lsp.load_scene(root)
    rows = lsp.stage_status(root, scene)
    print(f"{'layer':10} {'status':10} {'sha12':12}")
    for lid in lsp.STAGE_ORDER:
        if lid not in rows:
            continue
        r = rows[lid]
        print(f"{lid:10} {r['status']:10} {r['sha256'][:12]}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="创建 LSP 工程")
    p.add_argument("--spec", required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--tier", default="half", choices=["closeup", "half", "full"])
    p.add_argument("--out", required=True)
    p.add_argument("--palette", default=None)
    p.add_argument("--name", default=None)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("build", help="生成单个图层")
    p.add_argument("--lsp", required=True)
    p.add_argument("--only", required=True)
    p.add_argument("--detect-h", type=int, default=DETECT_H)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("preview", help="重出检查图")
    p.add_argument("--lsp", required=True)
    p.add_argument("--layer", required=True)
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("confirm", help="确认某层")
    p.add_argument("--lsp", required=True)
    p.add_argument("--layer", required=True)
    p.set_defaults(func=cmd_confirm)

    p = sub.add_parser("status", help="阶段台账")
    p.add_argument("--lsp", required=True)
    p.set_defaults(func=cmd_status)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
