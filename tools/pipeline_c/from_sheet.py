"""Derive a tachie sprite from a three-view character sheet.

Text-to-image cannot keep identity across independent runs, so the tachie is
cropped deterministically from the front view of the sheet instead of being
re-generated.  No re-sampling means the design is identical by construction.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

VIEWS = {"front": 0, "side": 1, "back": 2}


def _foreground_mask(img):
    px = np.asarray(img.convert("RGB"), dtype=np.int16)
    low = px.min(axis=2)
    spread = px.max(axis=2) - low
    return (low < 235) | (spread > 18)


def _segments(occupied, min_gap):
    segs, start, gap = [], None, 0
    for i, hit in enumerate(occupied):
        if hit:
            if start is None:
                start = i
            gap = 0
        elif start is not None:
            gap += 1
            if gap >= min_gap:
                segs.append((start, i - gap + 1))
                start, gap = None, 0
    if start is not None:
        segs.append((start, len(occupied)))
    return segs


def _strip_frame(img):
    """Blank thin frame lines drawn near the canvas border.

    A decorative rectangle spanning the full width would make every column
    non-background and break the three-view segmentation, so lines that sit in
    the outer 10% margin and cover most of the canvas are erased first.
    """
    arr = np.array(img.convert("RGB"), dtype=np.uint8)
    gray = arr.min(axis=2)
    h, w = gray.shape
    rows = np.where((gray < 245).mean(axis=1) > 0.8)[0]
    cols = np.where((gray < 245).mean(axis=0) > 0.8)[0]
    rows = rows[(rows < h * 0.10) | (rows > h * 0.90)]
    cols = cols[(cols < w * 0.10) | (cols > w * 0.90)]
    if rows.size == 0 and cols.size == 0:
        return img
    arr[rows, :, :] = 255
    arr[:, cols, :] = 255
    return Image.fromarray(arr)


def derive(sheet, out, view="front", crop="full", height=None, cut=0.50,
           pad=0.01):
    img = _strip_frame(Image.open(sheet))
    w, h = img.size
    mask = _foreground_mask(img)
    occupied = mask.sum(axis=0) > max(2, int(h * 0.005))
    segs = [s for s in _segments(occupied, max(8, int(w * 0.02)))
            if s[1] - s[0] > w * 0.05]
    idx = VIEWS.get(view, view)
    if not isinstance(idx, int) or idx < 0 or idx >= len(segs):
        raise RuntimeError(
            f"cannot find view {view!r}: detected {len(segs)} views in {sheet}")
    x0, x1 = segs[idx]
    part = mask[:, x0:x1]
    labels, count = ndimage.label(part)
    if count == 0:
        raise RuntimeError(f"empty view {view!r} in {sheet}")
    areas = np.bincount(labels.ravel())
    areas[0] = 0
    keep = areas > areas.max() * 0.1
    keep[0] = False
    ys, xs = np.where(keep[labels])
    if ys.size == 0:
        raise RuntimeError(f"empty view {view!r} in {sheet}")
    x0, x1 = x0 + int(xs.min()), x0 + int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    padx, pady = int((x1 - x0) * pad), int((y1 - y0) * pad)
    fig = img.crop((max(0, x0 - padx), max(0, y0 - pady),
                    min(w, x1 + padx), min(h, y1 + pady)))
    if crop in ("half", "knee"):
        fig = fig.crop((0, 0, fig.width, max(1, int(fig.height * cut))))
    elif crop != "full":
        raise RuntimeError(f"unknown crop mode: {crop}")
    if height and fig.height != height:
        scale = height / fig.height
        fig = fig.resize((max(1, round(fig.width * scale)), height),
                         Image.LANCZOS)
    dest = Path(out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fig.save(dest)
    return dest, fig.size


def _front_span(img):
    """Return ``(x0, x1)`` of the front view column range."""
    w, h = img.size
    mask = _foreground_mask(img)
    occupied = mask.sum(axis=0) > max(2, int(h * 0.005))
    segs = [s for s in _segments(occupied, max(8, int(w * 0.02)))
            if s[1] - s[0] > w * 0.05]
    if not segs:
        raise RuntimeError(f"no view found in sheet ({w}x{h})")
    return segs[0]


def redraw_front_face(sheet, out, spec, scale=2.0, half="left"):
    """Redraw the nose and mouth on the sheet's front view (deterministic).

    Text-to-image keeps shrinking the nose and drifting the mouth, so the sheet
    itself is corrected: the front view is the only one with a frontal face, so
    the side and back views are left untouched.
    """
    from . import brief, convert

    spec_doc = convert.schema.load(spec)
    effective, _ = brief.resolve_spec(spec_doc)
    tones = convert._skin_tones(effective)
    if not tones:
        raise RuntimeError(f"spec {spec} has no skin tones; cannot place the nose")
    img = _strip_frame(Image.open(sheet))
    arr = np.array(img.convert("RGB"))
    x0, x1 = _front_span(img)
    fixed, info = convert._redraw_nose(arr[:, x0:x1], *tones,
                                      scale=scale, half=half)
    fixed, mouth_info = convert._redraw_mouth(fixed, *tones)
    arr[:, x0:x1] = fixed
    info += mouth_info
    dest = Path(out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr).save(dest)
    return dest, info


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--view", default="front", choices=list(VIEWS))
    ap.add_argument("--crop", default="full", choices=["full", "half", "knee"])
    ap.add_argument("--height", type=int, default=None,
                    help="target pixel height (Lanczos upscale)")
    ap.add_argument("--cut", type=float, default=0.50,
                    help="crop ratio of figure height (0.50 hip, 0.76 knee)")
    ap.add_argument("--pad", type=float, default=0.01)
    ap.add_argument("--spec", default="",
                    help="with --spec, redraw the front-view nose and mouth")
    ap.add_argument("--nose-scale", type=float, default=1.5)
    ap.add_argument("--nose-half", default="left",
                    choices=("none", "left", "right"))
    args = ap.parse_args()
    if args.spec:
        fixed, info = redraw_front_face(args.sheet, args.sheet, args.spec,
                                        args.nose_scale, args.nose_half)
        for line in info:
            print(line)
        print(f"face fixed in place: {fixed}")
    dest, size = derive(args.sheet, args.out, args.view, args.crop,
                        args.height, args.cut, args.pad)
    print(f"derived {args.view}/{args.crop}: {dest} {size[0]}x{size[1]}")


if __name__ == "__main__":
    main()
