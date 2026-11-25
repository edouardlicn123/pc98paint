# -*- coding: utf-8 -*-
"""Simplified shading model for a flat AI illustration.

This follows the original tachie pipeline (matregion._shade_materials and
drawing.build_cloth_layers) instead of inventing a per-cause layer stack:

    * one merged illumination field per material
    * three declared tones per material (base / mid / deep) read from the
      reference painting, never derived by a runtime brightness formula
    * cast, fold and contact darkening are merged into the same field
    * the highlight is read from the art's own speculars

Layers: 10_base / 20_shade / 30_deep / 40_highlight / 50_composite.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import binary_closing, binary_dilation, binary_fill_holes, \
    label

from tools.tachie import shading
from tools.tachie.semantic_layers import _hsv, luminance, segment

ROOT = Path(__file__).resolve().parents[2]

# Tones calibrated against the reference painting (one ramp per material).
SPEC = {
    "hair":   ("#f1969b", "#c16b70", "#854145"),
    "face":   ("#fbebe1", "#e5cabb", "#c1a797"),
    "neck":   ("#fbefdf", "#e5cfb9", "#c1ab95"),
    "blouse": ("#fbefdf", "#ded2c2", "#b3a797"),
    "trim":   ("#7b544a", "#654137", "#4c322b"),
    "skirt":  ("#9f6d59", "#8a5c46", "#5f3b2c"),
    "bow":    ("#fcb378", "#e2a067", "#ab7244"),
    "shoe":   ("#1c1d1f", "#43464a", "#111113"),
    "leg0":   ("#fce5da", "#f0d8c8", "#d8b9a6"),
    "leg1":   ("#fce4da", "#f0d7c7", "#d8b8a5"),
}
DECAL = {"eye"}
CLOTH = {"blouse", "skirt", "trim", "bow"}


def _rgb(hexstr):
    hexstr = hexstr.lstrip("#")
    return np.array([int(hexstr[i:i + 2], 16) for i in (0, 2, 4)], np.float64)


def _bbox(mask):
    ys, xs = np.nonzero(mask)
    return int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())


def _keep(mask, min_px):
    return shading._keep_components(np.asarray(mask, bool), min_px)


def _clean(mask, min_px=200):
    m = binary_closing(np.asarray(mask, bool), iterations=2)
    return _keep(m, min_px)


def build(rgb, fg, masks, out_dir: Path):
    h, w, _ = rgb.shape
    light = shading.light_vector("upper-left")
    scale = max(1.0, w / 257.0)      # same local-scale convention as matregion
    lum = luminance(rgb) / 255.0

    base = np.zeros_like(rgb)
    mid = np.zeros_like(rgb)
    deep = np.zeros_like(rgb)
    hi = np.zeros_like(rgb)
    base_m = mid_m = deep_m = hi_m = np.zeros((h, w), bool)

    hair_front = np.zeros_like(fg)
    for name, m in masks.items():
        if name != "hair":
            continue
        for comp in _components(m, 800):
            if comp["area"] < 80000 and comp["y0"] > 0.25 * h:
                hair_front |= comp["mask"]

    for name, m in masks.items():
        if not m.any() or name not in SPEC:
            continue
        tone = [_rgb(c) for c in SPEC[name]]
        base[m] = tone[0]
        base_m |= m
        if name in DECAL:
            base[m] = rgb[m]          # eyes are a detail decal, not body light
            continue

        mid_b = np.zeros_like(m)
        deep_b = np.zeros_like(m)
        hi_b = np.zeros_like(m)

        if name == "hair":
            # Locks, not one cylinder: distance from each lock's own edge.
            mid_b, deep_b, _ = shading.directional_bands(
                m, light, (0.70, 0.28), min_px=200)
            _, sat, _ = _hsv(rgb / 255.0)
            hi_b = _clean(m & (lum >= 0.86) & (sat < 0.30), 40)
        elif name == "face":
            y0, y1, x0, x1 = _bbox(m)
            cx, cy = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
            rx, ry = max(1.0, 0.5 * (x1 - x0 + 1)), max(1.0, 0.5 * (y1 - y0 + 1))
            field = shading.ellipsoid_field(m, cx, cy, rx, ry, light,
                                            terminator=0.38)
            mid_b, _, _ = shading.field_bands(field, m, (0.30,), min_px=60)
            # Bangs above the eyes are the only hair that can shade the face.
            bangs = masks["hair"].copy()
            bangs[int(y0 + 0.35 * (y1 - y0)):, :] = False
            mid_b |= shading.cast_shadow(bangs, m, light, 0.007 * h)
        elif name == "neck":
            field = shading.cylindrical_field(m, light)
            mid_b, _, _ = shading.field_bands(field, m, (0.45,), min_px=30)
            mid_b |= shading.cast_shadow(masks["face"], m, light, 4.0 * scale)
        elif name in ("leg0", "leg1"):
            mid_b, deep_b, _ = shading.continuous_bands(
                m, light, (0.40, 0.80), min_px=80)
            mid_b |= shading.cast_shadow(masks["skirt"], m, light, 0.010 * h)
        elif name == "shoe":
            mid_b, _, _ = shading.directional_bands(
                m, -light, (0.55,), min_px=30)
            mid_b = _clean(mid_b, 100)
        else:                          # blouse / skirt / trim / bow
            field = shading.cylindrical_field(m, light)
            mid_b, deep_b, _ = shading.field_bands(field, m, (0.45, 0.78),
                                                   min_px=60)
            if name == "blouse":
                mid_b |= shading.cast_shadow(masks["trim"], m, light,
                                             3.0 * scale)
                if hair_front.any():
                    mid_b |= shading.cast_shadow(hair_front, m, light,
                                                 0.009 * h)
            if name == "skirt":
                mid_b |= shading.cast_shadow(masks["blouse"], m, light,
                                             0.005 * h)

        mid_b = _clean(mid_b & m, 200)
        deep_b = _clean(deep_b & mid_b, 150)
        mid_m |= mid_b
        deep_m |= deep_b
        mid[mid_b] = tone[1]
        deep[deep_b] = tone[2]

        if hi_b.any():
            hi_m |= hi_b
            hi[hi_b] = np.clip(tone[0] * 0.35 + 255.0 * 0.65, 0, 255)

    # The art's own strand / pleat / crease lines become the deep tone; no
    # growth, so pleats stay lines instead of dirty wedges.
    for name in ("hair", "skirt", "blouse", "bow"):
        m = masks.get(name)
        if m is None or not m.any():
            continue
        tone = [_rgb(c) for c in SPEC[name]]
        base_lum = float(np.median(lum[m]))
        stroke = m & (lum < base_lum * 0.76)
        stroke &= ~binary_dilation(~m, iterations=6)
        stroke = _keep(binary_closing(stroke, iterations=1), 60)
        deep_m |= stroke
        deep[stroke] = tone[2]

    out = rgb.copy()
    out[base_m] = base[base_m]
    out[mid_m] = mid[mid_m]
    out[deep_m] = deep[deep_m]
    out[hi_m] = hi[hi_m]

    out_dir.mkdir(parents=True, exist_ok=True)

    def save(arr, mask, name):
        rgba = np.zeros((h, w, 4), np.uint8)
        rgba[mask, :3] = np.clip(arr[mask], 0, 255).astype(np.uint8)
        rgba[mask, 3] = 255
        Image.fromarray(rgba, "RGBA").save(out_dir / name)

    save(base, base_m, "10_base.png")
    save(mid, mid_m, "20_shade.png")
    save(deep, deep_m, "30_deep.png")
    save(hi, hi_m, "40_highlight.png")
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(
        out_dir / "50_composite.png")
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).resize(
        (w // 2, h // 2), Image.LANCZOS).save(out_dir / "51_composite_half.png")

    lines = ["material  base      mid       deep      px"]
    for name in masks:
        if name not in SPEC:
            continue
        b, mi, d = SPEC[name]
        lines.append(f"{name:<9s} {b:<9s} {mi:<9s} {d:<9s} "
                     f"{int(masks[name].sum()):8d}")
    lines.append(f"layer px: base={int(base_m.sum())} shade={int(mid_m.sum())} "
                 f"deep={int(deep_m.sum())} hi={int(hi_m.sum())}")
    text = "\n".join(lines)
    (out_dir / "report.txt").write_text(text + "\n", encoding="utf-8")
    print(text)


def _components(mask, min_px):
    lab, n = label(mask)
    out = []
    for i in range(1, n + 1):
        c = lab == i
        if c.sum() < min_px:
            continue
        ys, xs = np.nonzero(c)
        out.append({"mask": c, "area": int(c.sum()), "y0": int(ys.min()),
                    "y1": int(ys.max())})
    return out


def main(src="output/ai_flat_test01.jpg", out="output/ai_semantic_simple"):
    rgb = np.asarray(Image.open(ROOT / src).convert("RGB")).astype(np.float64)
    fg, _, masks = segment(rgb)
    build(rgb, fg, masks, ROOT / out)


if __name__ == "__main__":
    main(*sys.argv[1:])
