# -*- coding: utf-8 -*-
"""Semantic cel-shading layers for a flat AI illustration.

Painting model (Love^2 reference): one key light from the upper-left-front.
Every shadow has a cause, and the cause decides which layer owns it:

    form      -- the surface turns away from the light (volume of a cylinder /
                 ellipsoid: hair mass, torso, each leg, each skirt panel)
    cast      -- one body part blocks the light for another part; the colour
                 belongs to the *receiver*, never to the occluder
    fold      -- the material's own drawn crease / strand / pleat
    ao        -- deep contact occlusion where two parts touch
    highlight -- specular or bounce band inside the lit area

The base layer is the local colour (material albedo).  Shadow bands select a
tone of the receiver material instead of inventing a new colour, so each
material keeps a 4-step ramp (base / mid / deep / highlight).

No palette quantization, no down-scaling.
"""
from __future__ import annotations

import colorsys
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import (binary_closing, binary_dilation, binary_fill_holes,
                           binary_opening, distance_transform_edt, label)

from tools.tachie import shading

ROOT = Path(__file__).resolve().parents[2]

SEEDS = {
    "hair": (242, 150, 158),
    "hair_dark": (196, 96, 118),
    "cream": (250, 239, 224),
    "brown": (150, 103, 85),
    "brown_dark": (112, 74, 63),
    "ink": (38, 28, 29),
    "shoe": (14, 9, 9),
    "bow_orange": (249, 132, 96),
    "bow_yellow": (252, 219, 140),
    "eye_green": (90, 150, 110),
}


# --------------------------------------------------------------------------
# colour helpers
# --------------------------------------------------------------------------
def _hsv(rgb):
    r, g, b = rgb[..., 0] / 255.0, rgb[..., 1] / 255.0, rgb[..., 2] / 255.0
    mx, mn = np.maximum(np.maximum(r, g), b), np.minimum(np.minimum(r, g), b)
    d = mx - mn
    s = d / (mx + 1e-6)
    h = np.zeros_like(mx)
    nz = d > 1e-6
    i = nz & (mx == r)
    h[i] = (((g[i] - b[i]) / d[i]) % 6.0) * 60.0
    i = nz & (mx == g)
    h[i] = ((b[i] - r[i]) / d[i] + 2.0) * 60.0
    i = nz & (mx == b)
    h[i] = ((r[i] - g[i]) / d[i] + 4.0) * 60.0
    return h, s, mx


def tone(rgb, value, sat=1.0, toward=None, amount=0.0):
    """Scale a single colour in HSV; optional blend toward a shadow tint."""
    r, g, b = (float(c) / 255.0 for c in np.asarray(rgb, np.float64)[:3])
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    out = np.array(colorsys.hsv_to_rgb(
        h, np.clip(s * sat, 0.0, 1.0), np.clip(v * value, 0.0, 1.0))) * 255.0
    if toward is not None and amount > 0.0:
        out = out * (1.0 - amount) + np.asarray(toward, np.float64) * amount
    return out


# Per-material 4-step ramp.  Values are (brightness factor, saturation factor)
# measured against the reference painting: warm skin and hair lose more value
# and gain more chroma in shadow, cloth loses value with almost no chroma gain.
RAMP = {
    "hair": dict(mid=(0.80, 1.18), deep=(0.55, 1.35)),
    "face": dict(mid=(0.90, 1.35), deep=(0.74, 1.65),
                 tint=(250, 172, 132), tint_amount=0.12),
    "neck": dict(mid=(0.90, 1.35), deep=(0.74, 1.65),
                 tint=(250, 172, 132), tint_amount=0.12),
    "leg0": dict(mid=(0.92, 1.30), deep=(0.78, 1.50),
                 tint=(252, 178, 140), tint_amount=0.10),
    "leg1": dict(mid=(0.92, 1.30), deep=(0.78, 1.50),
                 tint=(252, 178, 140), tint_amount=0.10),
    "blouse": dict(mid=(0.80, 1.04), deep=(0.62, 1.06),
                   tint=(150, 150, 168), tint_amount=0.08),
    "trim": dict(mid=(0.85, 1.05), deep=(0.62, 1.10)),
    "skirt": dict(mid=(0.82, 1.15), deep=(0.60, 1.22)),
    "bow": dict(mid=(0.87, 1.10), deep=(0.68, 1.15)),
    "shoe": dict(mid=(2.40, 1.00), deep=(0.60, 1.00), invert=True),
}
DEFAULT_RAMP = dict(mid=(0.84, 1.05), deep=(0.64, 1.12))


def luminance(rgb):
    return 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]


# --------------------------------------------------------------------------
# material segmentation
# --------------------------------------------------------------------------
def _largest(mask):
    lab, n = label(mask)
    if n == 0:
        return mask
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    return lab == sizes.argmax()


def _components(mask, min_px=300):
    lab, n = label(mask)
    out = []
    for i in range(1, n + 1):
        c = lab == i
        area = int(c.sum())
        if area < min_px:
            continue
        ys, xs = np.nonzero(c)
        out.append({"mask": c, "area": area, "y0": int(ys.min()),
                    "y1": int(ys.max()), "x0": int(xs.min()),
                    "x1": int(xs.max()),
                    "cy": float(ys.mean())})
    out.sort(key=lambda c: -c["area"])
    return out


def segment(rgb):
    """Split the flat illustration into material masks with spatial priors."""
    h, w, _ = rgb.shape
    bg = (rgb.min(2) > 242) & ((rgb.max(2) - rgb.min(2)) < 10)
    fg = binary_opening(binary_fill_holes(
        _largest(binary_closing(~bg, iterations=2))), iterations=1)

    names = list(SEEDS)
    seeds = np.array([SEEDS[k] for k in names], np.float64)
    px = rgb[fg]
    idx = np.full((h, w), -1, np.int16)
    idx[fg] = ((px[:, None, :] - seeds[None]) ** 2).sum(2).argmin(1)
    pick = {name: i for i, name in enumerate(names)}

    cream = idx == pick["cream"]
    cream_comps = _components(cream, 500)
    blouse = cream_comps[0]["mask"]
    legs, face, neck = [], None, None
    for comp in cream_comps[1:]:
        cy, cw = comp["cy"], comp["x1"] - comp["x0"]
        ch = comp["y1"] - comp["y0"]
        if comp["y0"] > 0.60 * h and ch > 2 * cw:      # legs
            legs.append(comp["mask"])
        elif comp["y1"] < 0.30 * h and cw > 0.12 * w and face is None:
            face = comp["mask"]
        elif comp["y1"] < 0.40 * h and neck is None:
            neck = comp["mask"]
    if face is None:
        raise RuntimeError("face material not found")
    if neck is None:
        neck = np.zeros_like(fg)

    brown = (idx == pick["brown"]) | (idx == pick["brown_dark"])
    brown_comps = _components(brown, 500)
    skirt = brown_comps[0]["mask"]
    browna = brown & ~skirt
    trim = np.zeros_like(fg)
    for comp in _components(browna, 600):
        if comp["y1"] < int(0.45 * h):        # collar band, cuffs, pocket
            trim |= comp["mask"]

    # The long hair is cut into locks by its own strand lines; keep every
    # sizeable piece so a single lock is not dropped as a speck.
    hair_src = ((idx == pick["hair"]) | (idx == pick["hair_dark"])) & \
        ~(trim | skirt | blouse | face | neck)
    for m in legs:
        hair_src &= ~m
    hair = np.zeros_like(fg)
    for comp in _components(hair_src, 800):
        hair |= comp["mask"]

    # The bow sits on the head; warm anti-aliasing elsewhere must not join it.
    bow_src = (idx == pick["bow_orange"]) | (idx == pick["bow_yellow"])
    bow = np.zeros_like(fg)
    for comp in _components(bow_src, 400):
        if comp["y1"] < int(0.35 * h):
            bow |= comp["mask"]
    bow = binary_closing(bow, iterations=2)

    # The green seed also catches cold anti-aliasing on every outline, so the
    # eyes are taken as the largest green blobs inside the head only.
    eye = np.zeros_like(fg)
    for comp in _components(idx == pick["eye_green"], 80):
        if comp["y1"] < int(0.30 * h):
            eye |= comp["mask"]
    eye = binary_fill_holes(binary_dilation(eye, iterations=2))

    # Near-black outlines share the shoe colour; keep only the shoes, which
    # are the dark blobs at the bottom of the figure.
    shoe = np.zeros_like(fg)
    low = fg & (luminance(rgb) < 0.30 * 255.0) & \
        (np.mgrid[0:h, 0:w][0] > int(0.85 * h))
    for comp in _components(low, 1500):
        shoe |= comp["mask"]
    shoe = binary_closing(shoe, iterations=2)

    masks = {
        "hair": hair, "face": face, "neck": neck, "blouse": blouse,
        "trim": trim, "skirt": skirt, "bow": bow, "eye": eye, "shoe": shoe,
    }
    for i, m in enumerate(legs):
        masks[f"leg{0 if i == 0 else 1}"] = m

    # Pink/red pixels inside a cream or skin component are hair strands that
    # cross it; hand them back to the hair so they do not become skin creases.
    hue, sat, _ = _hsv(rgb / 255.0)
    pink = ((hue > 335.0) | (hue < 12.0)) & (sat > 0.24)
    for name in ("face", "neck", "blouse"):
        moved = masks[name] & pink
        masks[name] = masks[name] & ~moved
        masks["hair"] |= moved

    # Pixels that no seed claimed (white hair shine, anti-aliasing) inherit the
    # nearest material so the base layer has no holes and the hair keeps its
    # specular specks for the highlight layer.
    ids = np.zeros((h, w), np.int16)
    for i, name in enumerate(masks, 1):
        ids[masks[name]] = i
    hole = fg & (ids == 0)
    if hole.any():
        _, nearest = distance_transform_edt(ids == 0, return_indices=True)
        ids[hole] = ids[nearest[0][hole], nearest[1][hole]]
    masks = {name: ids == i for i, name in enumerate(masks, 1)}
    return fg, ids, masks


# --------------------------------------------------------------------------
# layer construction
# --------------------------------------------------------------------------
PATTERN = {"bow": 0.55}      # painted pattern keeps its own albedo
DECAL = {"eye"}              # detail art, not body lighting
FOLD_SKIP = {"face", "neck", "leg0", "leg1", "trim", "shoe"}


def _erode_band(mask, px=3):
    return mask & ~binary_dilation(~mask, iterations=px)


def _sl(mask, pad=2):
    """Bounding-box slices so distance fields run on the part, not the page."""
    ys, xs = np.nonzero(mask)
    if not ys.size:
        return None
    return (slice(max(0, int(ys.min()) - pad), int(ys.max()) + pad + 1),
            slice(max(0, int(xs.min()) - pad), int(xs.max()) + pad + 1))


def _clean(mask, min_px=300, close=2):
    """Close pinholes and drop specks so a painted band has a clean edge."""
    m = binary_closing(np.asarray(mask, bool), iterations=close)
    return shading._keep_components(m, min_px)


def build(rgb, fg, masks, out_dir: Path):
    h, w, _ = rgb.shape
    light = shading.light_vector("upper-left")
    lum = luminance(rgb) / 255.0
    H = float(h)
    report = []

    base_rgb = np.zeros_like(rgb)
    mid_rgb = np.zeros_like(rgb)
    deep_rgb = np.zeros_like(rgb)
    cast_rgb = np.zeros_like(rgb)
    fold_rgb = np.zeros_like(rgb)
    ao_rgb = np.zeros_like(rgb)
    hi_rgb = np.zeros_like(rgb)
    base_m = np.zeros((h, w), bool)
    form_m = np.zeros((h, w), bool)
    form_deep_m = np.zeros((h, w), bool)
    cast_m = np.zeros((h, w), bool)
    fold_m = np.zeros((h, w), bool)
    ao_m = np.zeros((h, w), bool)
    hi_m = np.zeros((h, w), bool)
    owner = np.full((h, w), -1, np.int16)       # material id for the cause map
    cause = np.zeros((h, w), np.int16)         # 1 base 2 form 3 cast 4 fold 5 ao 6 hi
    ramps = {}

    names = [k for k in masks if masks[k].any()]
    for i, name in enumerate(names):
        owner[masks[name] & (owner < 0)] = i

    def put(arr, mask, colour):
        arr[mask] = np.asarray(colour, np.float64)

    for name in names:
        m = masks[name]
        area = int(m.sum())
        if area < 60:
            continue
        safe = _erode_band(m, 3)
        stats = safe if safe.sum() > 200 else m
        lit = stats & ~shading.away_side(m, light) & (lum > 0.35)
        if lit.sum() < 50:
            lit = stats
        base = np.median(rgb[lit], axis=0)
        # A near-black material (leather shoes) has no lit area; its gloss
        # specks would otherwise become the "base" colour.
        if float(np.median(lum[stats])) < 0.30 or lit.sum() < 50:
            base = np.median(rgb[stats], axis=0)
        if name in DECAL:
            base = np.median(rgb[stats], axis=0)
        cfg = dict(DEFAULT_RAMP)
        cfg.update(RAMP.get(name, {}))
        tint, amount = cfg.get("tint"), cfg.get("tint_amount", 0.0)
        mid = tone(base, *cfg["mid"], toward=tint, amount=amount)
        deep = tone(base, *cfg["deep"], toward=tint, amount=amount)
        hi = tone(base, 1.0, 0.45, toward=(255, 255, 255), amount=0.55)
        ramps[name] = (base, mid, deep, hi)

        put(base_rgb, m, base)
        base_m |= m
        cause[m & (cause == 0)] = 1

        if name in DECAL:
            continue
        if name in PATTERN:
            continue

        # ---- form: surface turning away from the light -------------------
        form_light = -light if cfg.get("invert") else light
        sl = _sl(m, 2)
        mid_b = np.zeros((h, w), bool)
        deep_b = np.zeros((h, w), bool)
        if name == "hair":
            # Hair is a bundle of locks, not one cylinder: a boundary-distance
            # band follows each lock's own contour instead of one bbox edge.
            sub_mid, sub_deep, _ = shading.directional_bands(
                m[sl], form_light, (0.45, 0.85), min_px=200)
        else:
            sub_mid, sub_deep, _ = shading.continuous_bands(
                m[sl], form_light, thresholds=(0.32, 0.72), min_px=40)
        mid_b[sl] = sub_mid
        deep_b[sl] = sub_deep
        mid_b = _clean(mid_b, 400) & m
        deep_b = _clean(deep_b, 300) & mid_b
        # A dark material gets its volume from the lit band, not from a
        # darker shadow band, so both form tones use the lifted colour.
        band_mid = mid
        band_deep = mid if cfg.get("invert") else deep
        form_m |= mid_b
        put(mid_rgb, mid_b, band_mid)
        form_deep_m |= deep_b
        put(deep_rgb, deep_b, band_deep)
        cause[mid_b] = 2
        cause[deep_b] = 2

        # ---- fold: the material's own crease / strand / pleat ------------
        # Skin and trim carry no crease of their own; their volume is form and
        # their contact darkening is cast/ao.
        if name in FOLD_SKIP:
            continue
        base_lum = float(np.median(lum[m]))
        stroke = m & (lum < base_lum * 0.78)
        stroke &= _erode_band(m, 7)          # interior creases only, no outline
        stroke = _clean(stroke, 120 if name == "hair" else 60, close=1)
        if stroke.any():
            limit = {"hair": 5, "skirt": 12, "blouse": 8}.get(name, 6)
            spread = int(np.clip(0.25 * float(
                np.percentile(shading.local_radius(shading.silhouette(m[sl])),
                              60)), 3, limit))
            grown = shading.cast_shadow(stroke, m, light, spread)
            fold = stroke | grown
            fold = _clean(fold, 150, close=1) & m
            fold_m |= fold
            put(fold_rgb, fold, tone(base, 0.72, 1.18))
            cause[fold] = 4

        # ---- highlight ---------------------------------------------------
        if name == "hair":
            bright = m & (lum > 0.86) & (_hsv(rgb)[1] < 0.30)
            bright = binary_closing(bright, iterations=1)
            if bright.any():
                hi_m |= bright
                put(hi_rgb, bright, tone(base, 1.0, 0.35,
                                         toward=(255, 255, 255), amount=0.72))
                cause[bright] = 6

    # ---- cast shadows: occluder -> receiver -------------------------------
    cast_pairs = [
        ("face", "neck", 0.006),
        ("bow", "hair", 0.004),
        ("trim", "blouse", 0.004), ("blouse", "skirt", 0.005),
    ]
    for leg in ("leg0", "leg1"):
        if leg in masks:
            cast_pairs.append(("skirt", leg, 0.010))
    hair_comps = _components(masks["hair"], 800)
    face_box = _bbox(masks["face"])
    blouse_box = _bbox(masks["blouse"])
    # Only the bangs above the eyes can throw a shadow onto the face; the rest
    # of the hair mass is beside or behind it.
    fy0, fy1 = face_box[0], face_box[1]
    bangs = masks["hair"].copy()
    bangs[int(fy0 + 0.35 * (fy1 - fy0)):, :] = False
    hair_on_face = bangs
    hair_front = np.zeros_like(fg)
    for comp in hair_comps:
        if _overlaps(comp, blouse_box) and comp["area"] < 80000:
            hair_front |= comp["mask"]
    pairs = list(cast_pairs)
    if hair_on_face.any():
        pairs.append(("__hair_face", "face", 0.007))
    if hair_front.any():
        pairs.append(("__hair_front", "blouse", 0.009))
        pairs.append(("__hair_front", "skirt", 0.009))

    for src_name, dst_name, depth in pairs:
        if src_name == "__hair_face":
            src = hair_on_face
        elif src_name == "__hair_front":
            src = hair_front
        else:
            src = masks.get(src_name)
        dst = masks.get(dst_name)
        if src is None or dst is None or not src.any() or not dst.any():
            continue
        sh = shading.cast_shadow(src, dst, light, max(3.0, depth * H))
        sh = _clean(sh, 400, close=2)
        if not sh.any():
            continue
        rec = ramps[dst_name]
        colour = tone(rec[2], 1.0, 1.05)
        cast_m |= sh
        put(cast_rgb, sh, colour)
        cause[sh] = 3
        report.append(f"cast  {src_name:>13s} -> {dst_name:<7s} "
                      f"px={int(sh.sum()):7d}")

    # ---- contact occlusion ------------------------------------------------
    ao_pairs = [("hair", "face"), ("hair", "blouse"), ("trim", "blouse"),
                ("bow", "hair"), ("blouse", "skirt"), ("hair", "skirt")]
    for leg in ("leg0", "leg1"):
        if leg in masks:
            ao_pairs.append(("skirt", leg))
    for src_name, dst_name in ao_pairs:
        src = masks.get(src_name)
        dst = masks.get(dst_name)
        if src is None or dst is None or not src.any() or not dst.any():
            continue
        sl = _sl(dst, 8)
        near = distance_transform_edt(~src[sl]) <= 4.0
        touch = np.zeros((h, w), bool)
        touch[sl] = dst[sl] & near
        touch &= ~binary_dilation(src, iterations=1)
        touch &= ~form_deep_m & ~cast_m & ~fold_m
        touch = _keep(touch, 80)
        if not touch.any():
            continue
        ao_m |= touch
        put(ao_rgb, touch, tone(ramps[dst_name][2], 0.86, 1.06))
        cause[touch] = 5

    # ---- pattern albedo (bow stripes) and decals (eyes) -------------------
    for name in names:
        m = masks[name]
        if name in PATTERN:
            put(base_rgb, m, rgb[m])
        if name in DECAL:
            put(base_rgb, m, rgb[m])

    # ---- composite: base, then form/cast/fold/ao, then highlight ---------
    comp = rgb.copy()
    comp[base_m] = base_rgb[base_m]
    comp[form_m] = mid_rgb[form_m]
    comp[form_deep_m] = deep_rgb[form_deep_m]
    comp[cast_m] = cast_rgb[cast_m]
    comp[fold_m] = fold_rgb[fold_m]
    comp[ao_m] = ao_rgb[ao_m]
    comp[hi_m] = hi_rgb[hi_m]

    out_dir.mkdir(parents=True, exist_ok=True)

    def save(arr, mask, name, alpha=255):
        rgba = np.zeros((h, w, 4), np.uint8)
        rgba[mask, :3] = np.clip(arr[mask], 0, 255).astype(np.uint8)
        rgba[mask, 3] = alpha
        Image.fromarray(rgba, "RGBA").save(out_dir / name)

    save(base_rgb, base_m, "10_base.png")
    form_only = np.zeros_like(rgb)
    form_only[form_m] = mid_rgb[form_m]
    form_only[form_deep_m] = deep_rgb[form_deep_m]
    save(form_only, form_m | form_deep_m, "20_form.png")
    save(deep_rgb, form_deep_m, "20_form_deep.png")
    save(cast_rgb, cast_m, "30_cast.png")
    save(fold_rgb, fold_m, "40_fold.png")
    save(ao_rgb, ao_m, "50_ao.png")
    save(hi_rgb, hi_m, "60_highlight.png")
    Image.fromarray(np.clip(comp, 0, 255).astype(np.uint8)).save(
        out_dir / "70_composite.png")
    Image.fromarray(np.clip(comp, 0, 255).astype(np.uint8)).resize(
        (w // 2, h // 2), Image.LANCZOS).save(out_dir / "71_composite_half.png")

    colours = np.array([
        [0, 0, 0], [245, 210, 160], [255, 90, 90], [60, 110, 255],
        [40, 190, 120], [150, 80, 220], [255, 240, 90]], np.uint8)
    cause_img = colours[np.clip(cause, 0, 6)]
    Image.fromarray(cause_img).resize((w // 3, h // 3), Image.NEAREST).save(
        out_dir / "80_cause_map.png")

    lines = ["material            base              mid               "
             "deep              hi                px"]
    for name in names:
        b, mi, d, hi = ramps[name]
        lines.append(f"{name:<14s} "
                     f"{_fmt(b):<17s} {_fmt(mi):<17s} {_fmt(d):<17s} "
                     f"{_fmt(hi):<17s} {int(masks[name].sum()):8d}")
    lines.append("")
    lines.append("layer px: base=%d form_mid=%d form_deep=%d cast=%d fold=%d "
                 "ao=%d hi=%d" % (int(base_m.sum()), int(form_m.sum()),
                                  int(form_deep_m.sum()), int(cast_m.sum()),
                                  int(fold_m.sum()), int(ao_m.sum()),
                                  int(hi_m.sum())))
    lines.extend(report)
    text = "\n".join(lines)
    (out_dir / "report.txt").write_text(text + "\n", encoding="utf-8")
    print(text)
    return comp


def _bbox(mask):
    ys, xs = np.nonzero(mask)
    return (int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())) \
        if ys.size else (0, 0, 0, 0)


def _overlaps(comp, box):
    y0, y1, x0, x1 = box
    return not (comp["y1"] < y0 or comp["y0"] > y1 or
                comp["x1"] < x0 or comp["x0"] > x1)


def _keep(mask, min_px):
    return shading._keep_components(mask, min_px)


def _fmt(c):
    r, g, b = np.clip(np.round(c), 0, 255).astype(int)
    return f"#{r:02x}{g:02x}{b:02x} ({r},{g},{b})"


def main(src="output/ai_flat_test01.jpg", out="output/ai_semantic"):
    rgb = np.asarray(Image.open(ROOT / src).convert("RGB")).astype(np.float64)
    fg, idx, masks = segment(rgb)
    print("materials:", {k: int(v.sum()) for k, v in masks.items()})
    build(rgb, fg, masks, ROOT / out)


if __name__ == "__main__":
    main(*sys.argv[1:])
