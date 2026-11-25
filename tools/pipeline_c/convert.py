# -*- coding: utf-8 -*-
"""HD illustration -> 640x400 PC-98 tachie PNG.

The colour step follows the project's PNG -> MAG path
(``tools/naiz_conv/mag_convert.py`` in the naiz repository): a sprite is
composited on a chroma key, every foreground pixel is assigned to the nearest
entry of a fixed character palette, and the background becomes the transparent
index.  No semantic material classification is involved, so a white blouse with
cool shadows and pale skin cannot be confused with each other.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[2]
_COMMON = ROOT / "tools" / "common"
_TACHIE = ROOT / "tools" / "tachie"
for _path in (_COMMON, _TACHIE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import bust_sample2 as bs  # noqa: E402
import palette98  # noqa: E402
import palette_for  # noqa: E402
import schema  # noqa: E402

from . import brief as brief_mod  # noqa: E402

W, H = 640, 400
MARGIN_Y = round(H * 0.05)  # 上下各 5%，即 20px

# PC-98 has 16 hardware colours and black/white are mandatory slots, so the
# materials may only claim 14.  Rich specs (5 hair tones + 3 skin tones + three
# cloth ramps) overflow, so each material keeps an evenly spaced subset.
_TONE_BUDGET = {"hair": 4, "skin": 3, "blouse": 2, "skirt": 2,
                "collar": 1, "bow": 1, "iris": 1, "eye": 1,
                "top": 2, "bottom": 2, "inner": 1, "accent": 1}


def _palette(effective):
    """Build the character's 16-colour palette from its own material refs."""
    pruned = copy.deepcopy(effective)
    for material in pruned.get("materials") or []:
        limit = _TONE_BUDGET.get(material.get("id"))
        refs = material.get("refs") or []
        if not limit or len(refs) <= limit:
            continue
        if limit == 1:
            material["refs"] = [refs[0]]
            continue
        if limit == 2 and len(refs) == 3:
            # Keep the lit and mid tones; dropping the mid tone makes cloth
            # shadows snap to an unrelated dark entry from another material.
            material["refs"] = [refs[0], refs[1]]
            continue
        step = (len(refs) - 1) / (limit - 1)
        keep = sorted({int(round(i * step)) for i in range(limit)})
        material["refs"] = [refs[i] for i in keep]
    return palette_for.build_palette(pruned)["colors"]


def _snap(color):
    """Snap to the PC-98 4-bit DAC grid (multiples of 17)."""
    return tuple(int(np.clip(round(value / 17.0) * 17.0, 0, 255))
                 for value in color)


def _fit_sprite(src, mode):
    """Crop/resize the foreground and report where it lands on the canvas."""
    bg = bs.background_mask(src)
    if mode == "closeup":
        crop, bg_crop = src, bg
        scale = min(W / src.width, (H - 2 * MARGIN_Y) / src.height)
        tw, th = round(src.width * scale), round(src.height * scale)
        ox, oy = (W - tw) // 2, (H - th) // 2
    else:
        ys, xs = np.where(~bg)
        pad = 8
        x0, x1 = max(0, xs.min() - pad), min(src.width, xs.max() + pad + 1)
        y0, y1 = max(0, ys.min() - pad), min(src.height, ys.max() + pad + 1)
        crop, bg_crop = src.crop((x0, y0, x1, y1)), bg[y0:y1, x0:x1]
        th = H - 2 * MARGIN_Y
        tw = round(crop.width * th / crop.height)
        if tw > W - 2 * MARGIN_Y:
            tw = W - 2 * MARGIN_Y
            th = round(crop.height * tw / crop.width)
        ox, oy = (W - tw) // 2, H - th - MARGIN_Y

    color = crop.resize((tw, th), Image.LANCZOS)
    rgb = bs.warm_gray_fix(np.array(color))
    bg_small = np.array(
        Image.fromarray((bg_crop * 255).astype(np.uint8)).resize(
            (tw, th), Image.BOX)
    ) > 127
    return rgb, bg_small, (ox, oy, tw, th)


def _skin_tones(effective):
    """Return (light, shadow) skin refs from the spec, or None."""
    for material in effective.get("materials", []):
        if material.get("id") in ("skin", "face"):
            refs = material.get("refs") or []
            if len(refs) >= 2:
                values = []
                for ref in (refs[0], refs[-1]):
                    value = ref.lstrip("#")
                    values.append(tuple(int(value[i:i + 2], 16) for i in (0, 2, 4)))
                return tuple(values)
    return None


# The legacy behaviour drew the shadow diamond at two thirds of the detected
# nose; ``--nose-scale 1.0`` keeps the source size and ``2.0`` doubles it.
NOSE_SCALE_DEFAULT = 2.0 / 3.0
_LUMA = np.array([0.299, 0.587, 0.114])


def _skin_mask(rgb, light, shadow):
    """Boolean mask of pixels close to the spec's light/shadow skin tones.

    White backgrounds and white shirts sit within ~18 Lab units of the pale
    skin ref, so a chroma gate is required: skin is always slightly warm and
    never near-neutral white.
    """
    lab = palette98.rgb_to_lab(rgb.astype(np.float64))
    refs = palette98.rgb_to_lab(np.asarray([light, shadow], dtype=np.float64))
    delta = np.linalg.norm(lab[:, :, None, :] - refs[None, None, :, :], axis=3)
    chroma = rgb.max(axis=2).astype(np.int16) - rgb.min(axis=2).astype(np.int16)
    neutral = (chroma < 12) | (rgb.min(axis=2) > 235)
    return (delta.min(axis=2) < 18.0) & ~neutral


def _face_box(mask):
    """Bounding box of the face skin, with the narrower neck cut off.

    The largest skin blob in the upper 60% is face+neck; the chin is the last
    row whose width is still at least 75% of the widest row, which stops the
    neck (about 40% of the face width) from stretching the box downward.
    """
    h, w = mask.shape
    upper = mask.copy()
    upper[int(h * 0.6):] = False
    labels, count = ndimage.label(upper)
    if count == 0:
        return None
    areas = np.bincount(labels.ravel())
    areas[0] = 0
    k = int(areas.argmax())
    if areas[k] < 0.004 * h * w:
        return None
    blob = labels == k
    widths = blob.sum(axis=1)
    rows = np.where(widths >= 0.75 * widths.max())[0]
    cols = np.where(blob[rows[0]:rows[-1] + 1].sum(axis=0) > 0)[0]
    if rows.size == 0 or cols.size == 0:
        return None
    return (int(cols[0]), int(cols[-1]) + 1, int(rows[0]), int(rows[-1]) + 1,
            int(widths.max()))


def _eye_pair(rgb, face):
    """Return ``(cx, eye_bottom, eye_distance)`` for the two eyes, or None.

    Eyes are the two largest dark blobs in the upper face band; lashes and
    irises merge into one blob per eye, while bangs shadows are thinner and
    much smaller in area.  The pair must be comparable in area and height.
    """
    x0, x1, y0, y1, _wmax = face
    fw, fh = x1 - x0, y1 - y0
    band_y1 = min(rgb.shape[0], y0 + int(0.80 * fh))
    band = rgb[y0:band_y1, x0:x1]
    if band.size == 0:
        return None
    dark = (band @ _LUMA) < 105.0
    labels, count = ndimage.label(dark)
    if count < 2:
        return None
    comps = []
    for k in range(1, count + 1):
        ys, xs = np.where(labels == k)
        area = ys.size
        if area < 0.0015 * band.size:
            continue
        comps.append((area, x0 + float(xs.mean()), y0 + float(ys.mean())))
    if len(comps) < 2:
        return None
    comps.sort(reverse=True)
    best = None
    for i in range(min(len(comps), 6)):
        for j in range(i + 1, min(len(comps), 6)):
            a1, x1_, y1_ = comps[i]
            a2, x2_, y2_ = comps[j]
            if max(a1, a2) > 2.5 * min(a1, a2):
                continue
            dx = abs(x1_ - x2_)
            if not 0.20 * fw <= dx <= 0.90 * fw:
                continue
            if abs(y1_ - y2_) > 0.20 * fh:
                continue
            score = a1 + a2
            if best is None or score > best[0]:
                best = (score, (x1_ + x2_) / 2.0, max(y1_, y2_), dx)
    if best is None:
        return None
    return best[1], best[2], best[3]


def _nose_geometry(rgb, face):
    """Return ``(center, base_size, span, mode)`` for the nose.

    Nose depth follows the eyes (about 0.6 inter-eye distances below the eye
    line) and its width is ~10% of the same distance, which matches a typical
    diamond nose.  Without a usable eye pair the chin ratio is used instead.
    """
    x0, x1, y0, y1, wmax = face
    eyes = _eye_pair(rgb, face)
    if eyes is not None:
        cx, eye_y, dist = eyes
        return (cx, eye_y + 0.60 * dist), 0.10 * dist, dist, "eyes"
    fh = y1 - y0
    return ((x0 + x1) / 2.0, y1 - 0.13 * fh), 0.05 * wmax, 0.30 * fh, "chin"


def _drawn_nose(rgb, skin, center, span):
    """Locate the nose the model actually drew near ``center``.

    The eye-derived guess is only a prediction; anchoring the redraw on it
    leaves the original shadow mark visible underneath.  The dark cluster
    closest to the guess is used as the real anchor when one is found.
    """
    cx, cy = center
    h, w = rgb.shape[:2]
    x0, x1 = int(max(0, cx - 0.45 * span)), int(min(w, cx + 0.45 * span + 1))
    y0, y1 = int(max(0, cy - 0.75 * span)), int(min(h, cy + 0.55 * span + 1))
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    win, m = rgb[y0:y1, x0:x1], skin[y0:y1, x0:x1]
    if m.sum() < 20:
        return None
    lum = win.mean(axis=2)
    dark = m & (lum < np.median(lum[m]) - 12)
    labels, count = ndimage.label(dark)
    best = None
    for i in range(1, count + 1):
        ys, xs = np.where(labels == i)
        if ys.size < 3:
            continue
        px, py = x0 + xs.mean(), y0 + ys.mean()
        dist = ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
        if best is None or dist < best[0]:
            best = (dist, px, py, (xs.max() - xs.min()) / 2.0,
                    (ys.max() - ys.min()) / 2.0, win[ys, xs].mean(axis=0))
    if best is None or best[0] > 0.55 * span:
        return None
    return best[1], best[2], (best[3], best[4]), best[5]


def _redraw_nose(rgb, light, shadow, scale=NOSE_SCALE_DEFAULT, half="none"):
    """Repaint the nose as a filled skin-shadow diamond, scaled by ``scale``.

    The diamond is redrawn instead of resized so that no blur or broken line
    art is introduced: the original nose is first covered with the surrounding
    skin tone, then a solid diamond is filled with the shadow ref (no outline).
    """
    skin = _skin_mask(rgb, light, shadow)
    face = _face_box(skin)
    if face is None:
        return rgb, ["NOSE: WARN face skin not found; nose left unchanged"]
    (cx, cy), base, span, mode = _nose_geometry(rgb, face)
    drawn = _drawn_nose(rgb, skin, (cx, cy), span)
    extent = (0.0, 0.0)
    if drawn is not None:
        cx, cy, extent, fill_rgb = drawn
        mode = f"{mode}+drawn"
        a = max(1.0, 0.50 * base * scale)
        b = max(1.4, 0.70 * base * scale)
        # Idempotency: the mark already is our own diamond at the target size
        # (a half diamond is narrower, so only the height can be compared).
        if (np.abs(np.asarray(fill_rgb, float) - np.asarray(shadow, float)).max() <= 30
                and abs(extent[1] - b) <= max(1.5, 0.25 * b)
                and extent[0] <= a + 1.5):
            return rgb, [
                f"NOSE: skip already fixed center=({cx:.0f},{cy:.0f}) "
                f"half=({extent[0]:.1f},{extent[1]:.1f}) scale={scale:.2f}"]

    a = max(1.0, 0.50 * base * scale)
    b = max(1.4, 0.70 * base * scale)
    h, w = rgb.shape[:2]
    yy, xx = np.ogrid[:h, :w]
    # Erase the whole mark that is currently drawn (not a fixed footprint), so
    # redrawing with a smaller scale never leaves the previous nose behind.
    ra = max(1.0, 0.55 * base, extent[0] + 1.0)
    rb = max(1.4, 0.75 * base, extent[1] + 1.0)
    ell = ((xx - cx) / ra) ** 2 + ((yy - cy) / rb) ** 2
    erase = ell <= 1.0
    ring = (ell <= 2.6) & ~erase & skin
    fill = np.median(rgb[ring], axis=0) if ring.any() else np.asarray(light, float)
    out = rgb.copy()
    out[erase] = fill
    dia = np.abs(xx - cx) / a + np.abs(yy - cy) / b <= 1.0
    if half == "left":
        dia &= xx <= cx
    elif half == "right":
        dia &= xx >= cx
    out[dia] = shadow
    return out, [
        f"NOSE: center=({cx:.0f},{cy:.0f}) base={base:.1f} "
        f"half=({a:.1f},{b:.1f}) scale={scale:.2f} half={half} at={mode}"
    ]


def _drawn_mouth(rgb, skin, center, span):
    """Find the faint mouth marks just below the nose.

    The mouth is drawn much lighter than the nose, so the band is kept tight
    (narrow x, 0.20–0.42 inter-eye distances down) and only small marks are
    accepted; anything wider/taller is blush or a cheek edge.  Returns the
    union bbox of the marks, or ``None``.
    """
    cx, cy = center
    h, w = rgb.shape[:2]
    x0, x1 = int(max(0, cx - 0.18 * span)), int(min(w, cx + 0.18 * span + 1))
    y0 = int(max(0, cy + 0.18 * span))
    y1 = int(min(h, cy + 0.44 * span + 1))
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    win, m = rgb[y0:y1, x0:x1], skin[y0:y1, x0:x1]
    if m.sum() < 20:
        return None
    lum = win.mean(axis=2)
    # Marks are not necessarily skin-coloured (an already redrawn arc is line
    # coloured), so only the threshold comes from skin; the band is inside the
    # face already.
    dark = lum < np.median(lum[m]) - 12
    labels, count = ndimage.label(dark)
    hits = []
    for i in range(1, count + 1):
        ys, xs = np.where(labels == i)
        if not 3 <= ys.size <= 0.04 * h * w:
            continue
        bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
        if bw > 0.35 * span or bh > 0.13 * span:
            continue
        hits.append((xs.min() + x0, xs.max() + x0, ys.min() + y0, ys.max() + y0))
    if not hits:
        return None
    return (min(h[0] for h in hits), max(h[1] for h in hits),
            min(h[2] for h in hits), max(h[3] for h in hits))


def _line_color(rgb, face):
    """Darkest 12% of the face box: the brown line colour used in the art."""
    x0, x1, y0, y1, _wmax = face
    win = rgb[y0:y1, x0:x1]
    lum = win.mean(axis=2)
    thresh = np.percentile(lum, 12.0)
    dark = lum <= thresh
    if dark.sum() < 4:
        return np.asarray((76, 37, 31), dtype=float)
    return win[dark].mean(axis=0)


MOUTH_INK = 0.70  # arc ink depth: 30% lighter than the art's line colour


def _redraw_mouth(rgb, light, shadow, width=0.11, curve=0.06):
    """Repaint the mouth as one thin smile arc anchored on the drawn ends.

    Both endpoints of the mouth line drawn in the art are kept; the stroke only
    dips downwards in between, so the arc sits exactly where the mouth was.
    The old marks are removed with a 5x5 median filter (thin marks are replaced
    by surrounding skin without a flat patch) and the arc is drawn in the art's
    own line colour.
    """
    skin = _skin_mask(rgb, light, shadow)
    face = _face_box(skin)
    if face is None:
        return rgb, ["MOUTH: WARN face skin not found; mouth left unchanged"]
    (px, py), _base, span, mode = _nose_geometry(rgb, face)
    nose = _drawn_nose(rgb, skin, (px, py), span)
    if nose is not None:
        px, py = nose[0], nose[1]
        mode = f"{mode}+drawn"
    hw = max(3.0, width * span)
    depth = curve * span
    thick = max(1, int(round(0.022 * span)))
    line = _line_color(rgb, face)
    # Ink depth: blend the line colour with the surrounding skin so the arc is
    # 30% lighter than the art's own line colour (2026-11-25 user request).
    skin_med = np.median(rgb[skin], axis=0)
    ink = line * MOUTH_INK + skin_med * (1.0 - MOUTH_INK)
    mx, my = px, py + 0.30 * span
    marks = _drawn_mouth(rgb, skin, (px, py), span)
    if marks is not None:
        # The two ends of the drawn mouth line are the anchors: the arc starts
        # and ends exactly there and only dips downwards in between.
        mx = (marks[0] + marks[1]) / 2.0
        hw = max(2.0, (marks[1] - marks[0]) / 2.0)
        # Anchor the stroke's centre line half a thickness below the detected
        # top row: the antialiased top edge then lands on the same row again,
        # which keeps repeated runs pixel-identical.
        my = float(marks[2]) + thick / 2.0
        mode = f"{mode}+marks"
        # Idempotency: probe five points along the arc; a JPEG-shifted bbox of
        # an already redrawn arc would otherwise creep one pixel per run.
        probe = sum(
            1 for u in (-0.8, -0.4, 0.0, 0.4, 0.8)
            if 0 <= int(round(my + depth * (1.0 - u * u))) < rgb.shape[0]
            and np.abs(rgb[int(round(my + depth * (1.0 - u * u))),
                           int(round(mx + u * hw))].astype(float) - ink).max() <= 45)
        if probe >= 4:
            return rgb, [f"MOUTH: skip already fixed center=({mx:.0f},{my:.0f}) "
                         f"half_w={hw:.1f}"]
    out = rgb.copy()
    # Clear the band between/under the anchors so no dash or previous arc
    # survives.  The band must not be limited to skin pixels: the marks to be
    # removed are exactly the non-skin (darker) ones, so the mask would keep
    # them and leave residue under the new arc.
    bx0 = int(max(0, mx - hw - 3))
    bx1 = int(min(rgb.shape[1], mx + hw + 4))
    by0 = int(max(0, my - 4))
    by1 = int(min(rgb.shape[0], my + depth + thick + 3))
    med = ndimage.median_filter(rgb, size=(5, 5, 1))
    out[by0:by1, bx0:bx1] = med[by0:by1, bx0:bx1]
    half_t = thick / 2.0
    for x in range(int(round(mx - hw)), int(round(mx + hw)) + 1):
        u = (x - mx) / hw
        y = my + depth * (1.0 - u * u)
        for yy in range(int(y - half_t) - 1, int(y + half_t) + 2):
            if not 0 <= yy < out.shape[0]:
                continue
            cov = min(1.0, max(0.0, half_t + 0.5 - abs(yy + 0.5 - y)))
            if cov <= 0.0:
                continue
            out[yy, x] = (np.asarray(out[yy, x], dtype=float) * (1.0 - cov)
                          + ink * cov).round().astype(np.uint8)
    return out, [
        f"MOUTH: center=({mx:.0f},{my:.0f}) half_w={hw:.1f} depth={depth:.1f} "
        f"thick={thick} width={2 * hw + 1:.0f} at={mode} ink={MOUTH_INK:.0%} "
        f"line=#{int(ink[0]):02x}{int(ink[1]):02x}{int(ink[2]):02x}"
    ]


def _map_to_palette(rgb, palette):
    """Assign every pixel to its nearest palette entry (CIELAB distance)."""
    pal = np.asarray([_snap(color) for color in palette], dtype=np.float64)
    tree = cKDTree(palette98.rgb_to_lab(pal))
    _, index = tree.query(palette98.rgb_to_lab(rgb.astype(np.float64)))
    return index.reshape(rgb.shape[:2]), pal


def to_pc98(spec_path, src_image, mode, out_png, palette_path=None,
            nose_scale=NOSE_SCALE_DEFAULT, nose_half="none"):
    """Render ``src_image`` to a transparent 640x400 sprite at ``out_png``."""
    spec = schema.load(spec_path)
    effective, _ = brief_mod.resolve_spec(spec)
    if palette_path:
        pal = palette98.load(palette_path)
    else:
        if not effective.get("materials"):
            raise ValueError(
                f"spec {spec_path} resolved without materials; "
                "cannot build the character palette")
        # The character owns its 16-slot palette: build it from the material
        # refs instead of falling back to the global bs.PALETTE, which has no
        # pink/hair ramps and snaps the hair to white.
        pal = _palette(effective)

    src = Image.open(src_image).convert("RGB")
    tones = _skin_tones(effective)
    if tones:
        # Recolour at full source resolution: the diamond is only ~10 px wide
        # after _fit_sprite, too small for the ring detector.
        rgb_src, info = _redraw_nose(np.array(src), *tones, scale=nose_scale,
                                     half=nose_half)
        for line in info:
            print(line)
        src = Image.fromarray(rgb_src)
    rgb, bg_small, (ox, oy, tw, th) = _fit_sprite(src, mode)
    index, pal = _map_to_palette(rgb, pal)

    # Index 0 is the transparent slot; visible colours start at 1.
    canvas = np.zeros((H, W), dtype=np.uint8)
    block = np.zeros((th, tw), dtype=np.uint8)
    block[~bg_small] = index[~bg_small].astype(np.uint8) + 1
    canvas[oy:oy + th, ox:ox + tw] = block

    out = Path(out_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("P", (W, H))
    flat = [0, 0, 0]
    for color in pal:
        flat.extend(int(value) for value in color)
    image.putpalette(flat)
    image.putdata(canvas.ravel().tolist())
    image.save(out, transparency=0)
    return out
