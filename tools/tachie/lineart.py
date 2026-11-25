# -*- coding: utf-8 -*-
"""Line-art stage (lineart) for the LSP tachie pipeline.

The line art is *measured*, never hand-authored per character:

* ``structure.json``   -> skeleton (head axis, shoulders, waist, pelvis, limbs);
* material-region masks -> visible part boundaries (hair, skin, blouse,
  collar, skirt, bow, iris) traced as smooth loops;
* resolved archetype (``body``/``face``/``hair``) and outfit descriptors
  -> parametric details (eyes, brows, nose, mouth, buttons, pleats, stripes).

This keeps the renderer character-independent: any character that supplies the
same three data sources produces a line drawing without code changes.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import label

# Loop area (working px^2) below which a traced loop is treated as noise.
MIN_LOOP_AREA = 2200.0
CONNECT8 = np.ones((3, 3), dtype=bool)

# Marching-squares case table: corner bits tl=8, tr=4, br=2, bl=1.
# Each entry lists segments between edge midpoints (top/right/bottom/left).
_CASES = {
    0: (), 15: (),
    1: ((3, 2),), 2: ((2, 1),), 3: ((3, 1),), 4: ((0, 1),),
    5: ((3, 0), (2, 1)), 6: ((0, 2),), 7: ((3, 0),),
    8: ((0, 3),), 9: ((0, 2),), 10: ((0, 1), (3, 2)),
    11: ((0, 1),), 12: ((3, 1),), 13: ((2, 1),), 14: ((3, 2),),
}


def role_masks(idx: np.ndarray, materials: list) -> dict:
    """Map every material role to a merged boolean mask."""
    out = {}
    for i, m in enumerate(materials):
        role = m.get("role")
        if not role:
            continue
        if role not in out:
            out[role] = np.zeros(idx.shape, dtype=bool)
        out[role] |= (idx == i)
    return out


def _raw_segments(mask: np.ndarray):
    p = np.pad(mask.astype(np.uint8), 1)
    tl = p[:-1, :-1]
    tr = p[:-1, 1:]
    bl = p[1:, :-1]
    br = p[1:, 1:]
    case = (tl << 3) | (tr << 2) | (br << 1) | bl
    active = (case > 0) & (case < 15)
    ys, xs = np.nonzero(active)
    segs = []
    for y, x in zip(ys.tolist(), xs.tolist()):
        pairs = _CASES[int(case[y, x])]
        pts = {
            0: (x - 0.5, float(y - 1)),
            1: (float(x), y - 0.5),
            2: (x - 0.5, float(y)),
            3: (float(x - 1), y - 0.5),
        }
        for a, b in pairs:
            segs.append((pts[a], pts[b]))
    return segs


def _link_segments(segs):
    """Chain unordered marching-squares segments into loops."""
    from collections import defaultdict

    def key(p):
        return (int(round(p[0] * 2)), int(round(p[1] * 2)))

    adj = defaultdict(list)
    for i, (a, b) in enumerate(segs):
        adj[key(a)].append(i)
        adj[key(b)].append(i)
    used = set()
    loops = []
    for i in range(len(segs)):
        if i in used:
            continue
        used.add(i)
        a, b = segs[i]
        start = key(a)
        loop = [a, b]
        cur = key(b)
        closed = False
        while True:
            nxt = [j for j in adj[cur] if j not in used]
            if not nxt:
                break
            j = nxt[0]
            used.add(j)
            c, d = segs[j]
            step = d if key(c) == cur else c
            loop.append(step)
            cur = key(step)
            if cur == start:
                closed = True
                break
        if len(loop) >= 4:
            loops.append((np.array(loop, dtype=np.float64), closed))
    return loops


def _poly_area(pts: np.ndarray) -> float:
    x, y = pts[:, 0], pts[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def _chaikin(pts: np.ndarray, iterations: int = 2, closed: bool = True,
             max_points: int = 320) -> np.ndarray:
    # Long mask boundaries would explode under Chaikin and make PIL joints
    # extremely slow, so decimate first; the curve stays visually identical.
    if len(pts) > max_points:
        step = int(math.ceil(len(pts) / float(max_points)))
        pts = pts[::step]
        if len(pts) < 4:
            return pts
    for _ in range(iterations):
        n = len(pts)
        if n < 3:
            return pts
        out = []
        span = range(n) if closed else range(n - 1)
        for i in span:
            p = pts[i]
            q = pts[(i + 1) % n]
            out.append(0.75 * p + 0.25 * q)
            out.append(0.25 * p + 0.75 * q)
        pts = np.array(out)
    return pts


def _smooth_points(pts: np.ndarray, closed: bool) -> np.ndarray:
    """Low-pass the traced polygon to remove mask-grid stair steps."""
    if len(pts) < 5:
        return pts
    if closed:
        return 0.25 * np.roll(pts, 1, axis=0) + 0.5 * pts \
            + 0.25 * np.roll(pts, -1, axis=0)
    out = pts.copy()
    out[1:-1] = 0.25 * pts[:-2] + 0.5 * pts[1:-1] + 0.25 * pts[2:]
    return out


def trace_loops(mask: np.ndarray, scale: float, min_area: float = MIN_LOOP_AREA):
    """Return ``(points, closed)`` loops in working coordinates for a mask."""
    if not mask.any():
        return []
    clipped = mask.copy()
    # Never trace along the crop frame: keep limbs cropped by the canvas open.
    clipped[0, :] = False
    clipped[-1, :] = False
    clipped[:, 0] = False
    clipped[:, -1] = False
    mh, mw = clipped.shape
    loops = []
    for pts, closed in _link_segments(_raw_segments(clipped)):
        work = pts * scale
        if _poly_area(work) < min_area:
            continue
        # A contour that reaches the crop frame belongs to a cut-off limb:
        # drop the frame-following run and keep it open (no closing stroke).
        at_frame = ((work[:, 0] < 0.6 * scale) | (work[:, 0] > (mw - 1.6) * scale)
                    | (work[:, 1] < 0.6 * scale) | (work[:, 1] > (mh - 1.6) * scale))
        if at_frame.any():
            closed = False
            work = work[~at_frame]
            if len(work) < 4:
                continue
        work = _smooth_points(_smooth_points(work, closed), closed)
        loops.append((_chaikin(work, 2, closed), closed))
    return loops


def _components(mask: np.ndarray, min_area: int):
    lab, n = label(mask, structure=CONNECT8)
    out = []
    for i in range(1, n + 1):
        ys, xs = np.where(lab == i)
        if len(ys) < min_area:
            continue
        out.append((int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max()),
                    float(np.median(xs)), float(np.median(ys)), len(ys)))
    return out


def _span_at(mask: np.ndarray, row: int, band: int = 2):
    row = int(np.clip(row, 0, mask.shape[0] - 1))
    ys, xs = np.where(mask[max(0, row - band):row + band + 1])
    if xs.size < 4:
        return None
    return float(np.percentile(xs, 3)), float(np.percentile(xs, 97))


def _axis_x(structure: dict, y: float) -> float:
    head = structure["head"]
    axis = head.get("axis") or [[head["x"], head["top"]], head["chin"]]
    (x0, y0), (x1, y1) = axis
    if abs(y1 - y0) < 1e-6:
        return x0
    t = float(np.clip((y - y0) / (y1 - y0), -1.0, 2.0))
    return x0 + (x1 - x0) * t


def _offset_loop(pts: np.ndarray, distance: float) -> np.ndarray:
    """Move a closed loop inward by ``distance`` along its local normal."""
    if len(pts) < 4:
        return pts
    centre = pts.mean(axis=0)
    prev, nxt = np.roll(pts, 1, axis=0), np.roll(pts, -1, axis=0)
    tangent = nxt - prev
    norm = np.hypot(tangent[:, 0], tangent[:, 1])
    norm[norm < 1e-6] = 1.0
    normal = np.stack([-tangent[:, 1] / norm, tangent[:, 0] / norm], axis=1)
    toward = centre - pts
    flip = (normal * toward).sum(axis=1) < 0
    normal[flip] *= -1.0
    return pts + normal * distance


class _Pen:
    def __init__(self, width: int, height: int, ink, supersample: int = 2):
        self.ss = supersample
        self.img = Image.new("RGBA", (width * supersample, height * supersample),
                             (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.img)
        self.ink = (int(ink[0]), int(ink[1]), int(ink[2]), 255)

    def loop(self, pts, width, color=None):
        if len(pts) < 2:
            return
        colour = self.ink if color is None else color
        seq = [(float(x) * self.ss, float(y) * self.ss) for x, y in pts]
        self.draw.line(seq + [seq[0]], fill=colour,
                       width=max(1, int(round(width * self.ss))), joint="curve")

    def open(self, pts, width, color=None):
        if len(pts) < 2:
            return
        colour = self.ink if color is None else color
        seq = [(float(x) * self.ss, float(y) * self.ss) for x, y in pts]
        self.draw.line(seq, fill=colour,
                       width=max(1, int(round(width * self.ss))), joint="curve")

    def circle(self, cx, cy, r, width, fill=None):
        box = [(cx - r) * self.ss, (cy - r) * self.ss,
               (cx + r) * self.ss, (cy + r) * self.ss]
        colour = self.ink if fill is None else fill
        self.draw.ellipse(box, outline=self.ink if fill is not None else colour,
                          fill=fill, width=max(1, int(round(width * self.ss))))

    def quad(self, p0, p1, p2, width, steps=18):
        ts = np.linspace(0.0, 1.0, steps)
        p0, p1, p2 = map(np.asarray, (p0, p1, p2))
        pts = [((1 - t) ** 2) * p0 + 2 * (1 - t) * t * p1 + (t ** 2) * p2
               for t in ts]
        self.open(np.array(pts), width)

    def image(self):
        return self.img.resize((self.img.width // self.ss,
                                self.img.height // self.ss), Image.LANCZOS)


def _eye_boxes(eye_mask: np.ndarray, scale: float, head: dict):
    comps = _components(eye_mask, max(12, int(eye_mask.size * 0.00002)))
    boxes = []
    for x0, x1, y0, y1, cx, cy, area in comps:
        wx, wy = cx * scale, cy * scale
        if wy > head["chin"][1] + 0.25 * (head["chin"][1] - head["top"]):
            continue
        if x1 - x0 < 3 or y1 - y0 < 3:
            continue
        boxes.append(((x0 + x1) * 0.5 * scale, (y0 + y1) * 0.5 * scale,
                      max(1.5, (x1 - x0) * 0.5 * scale),
                      max(1.5, (y1 - y0) * 0.5 * scale), area))
    boxes.sort(key=lambda b: b[0])
    if len(boxes) > 2:
        boxes = sorted(boxes, key=lambda b: b[4], reverse=True)[:2]
        boxes.sort(key=lambda b: b[0])
    return boxes


def _catmull_rom(points, samples: int = 14) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < 3:
        return pts
    ext = np.vstack([pts[0] - (pts[1] - pts[0]), pts,
                     pts[-1] + (pts[-1] - pts[-2])])
    out = []
    for i in range(len(pts) - 1):
        p0, p1, p2, p3 = ext[i], ext[i + 1], ext[i + 2], ext[i + 3]
        for t in np.linspace(0.0, 1.0, samples, endpoint=False):
            t2, t3 = t * t, t * t * t
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t
                              + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    out.append(pts[-1])
    return np.array(out)


def _draw_face_outline(pen, structure, features, eyes_y):
    """Visible face contour from the head axis + face-width ratio.

    Tracing the skin mask directly follows hair wisps and produces a jagged
    silhouette, so the face is rebuilt from the *structure* instead.
    """
    head = structure["head"]
    base = getattr(pen, "base", 1.0)
    chin_y = head["chin"][1]
    top = head["top"]
    head_h = max(1.0, chin_y - top)
    ratio = float((features.get("body") or {}).get("face_width_ratio", 0.66))
    half = max(0.16 * head_h, 0.5 * ratio * 2.0 * head["rx"])
    eye_y = eyes_y if eyes_y else top + 0.70 * head_h
    temple_y = eye_y - 0.055 * head_h
    chin_x = _axis_x(structure, chin_y)
    # Jaw points are interpolated between the eye line and the chin so the
    # contour always descends monotonically (no zig-zag / beak).
    jaw1_y = eye_y + 0.35 * (chin_y - eye_y)
    jaw2_y = eye_y + 0.70 * (chin_y - eye_y)
    left = [
        (_axis_x(structure, temple_y) - half, temple_y),
        (chin_x - 0.99 * half, jaw1_y),
        (chin_x - 0.72 * half, jaw2_y),
        (chin_x - 0.10 * half, chin_y),
    ]
    right = [(2.0 * _axis_x(structure, y) - x, y) for x, y in left]
    pen.open(_catmull_rom(left), 1.02 * base)
    pen.open(_catmull_rom(right), 1.02 * base)
    # Rounded chin instead of a pointed Catmull-Rom cusp.
    pen.quad(left[-1], (chin_x, chin_y + 0.035 * head_h), right[-1], 1.02 * base)

    # Neck: two tapered sides from under the jaw to the collar line.
    neck_top = chin_y + 0.012 * head_h
    neck_bot = min(float(structure.get("shoulder_y", chin_y + 0.2 * head_h))
                   + 0.015 * head_h, chin_y + 0.24 * head_h)
    if neck_bot > neck_top + 0.02 * head_h:
        for sign in (-1.0, 1.0):
            x_top = _axis_x(structure, neck_top) + sign * 0.095 * head_h
            x_bot = _axis_x(structure, neck_bot) + sign * 0.115 * head_h
            pen.open(_catmull_rom([(x_top, neck_top), (x_bot, neck_bot)],
                                  samples=10), 0.9 * base)


def _draw_face(pen, structure, masks, scale, features):
    head = structure["head"]
    top = head["top"]
    chin_y = head["chin"][1]
    head_h = max(1.0, chin_y - top)
    eyes = _eye_boxes(masks.get("eye", np.zeros((1, 1), bool)), scale, head)
    face = (features.get("face") or {})
    base = getattr(pen, "base", 1.0)
    markings = [str(m) for m in (face.get("markings") or [])]
    eyes_y = float(np.median([b[1] for b in eyes])) if eyes else None
    _draw_face_outline(pen, structure, features, eyes_y)
    for cx, cy, rx, ry, _area in eyes:
        ew = 2.25 * rx
        eh = 1.65 * ry
        # Upper lid (heavier lash) and lower lid.
        pen.quad((cx - ew / 2, cy + 0.12 * eh), (cx, cy - 0.95 * eh),
                 (cx + ew / 2, cy + 0.12 * eh), 1.05 * base)
        pen.quad((cx - ew / 2, cy + 0.12 * eh), (cx, cy + 0.72 * eh),
                 (cx + ew / 2, cy + 0.12 * eh), 0.7 * base)
        iris_r = 0.92 * min(rx, ry)
        pen.circle(cx, cy, iris_r, 0.55 * base)
        pen.circle(cx, cy + 0.05 * ry, 0.34 * iris_r, 0.0, fill=pen.ink)
        pen.circle(cx - 0.34 * rx, cy - 0.36 * ry, 0.22 * iris_r,
                   0.0, fill=(255, 255, 255, 255))
        # Brow: thin arched stroke above the eye.
        bx = cx
        by = cy - 1.65 * ry
        half = 1.15 * ew / 2
        pen.quad((bx - half, by + 0.10 * half), (bx, by - 0.20 * half),
                 (bx + half, by), 0.95 * base)
        if "freckles" in markings:
            for i in range(3):
                fx = cx + (i - 1) * 0.55 * rx
                pen.circle(fx, cy + 0.95 * ry, max(1.4, 0.10 * rx), 0.0,
                           fill=pen.ink)
        if "blush" in markings:
            for i in range(3):
                bx0 = cx - 1.5 * rx + i * 0.55 * rx
                pen.open([(bx0, cy + 1.35 * ry), (bx0 + 0.28 * rx, cy + 1.12 * ry)],
                         0.5 * base)
    # Nose tick and mouth on the face midline.
    eye_y = float(np.median([b[1] for b in eyes])) if eyes else top + 0.7 * head_h
    nose_y = eye_y + 0.105 * head_h
    nx = _axis_x(structure, nose_y)
    pen.open([(nx, nose_y - 0.012 * head_h), (nx + 0.014 * head_h, nose_y)],
             0.75 * pen_width(pen, 0.42))
    mouth_y = eye_y + 0.195 * head_h
    mx = _axis_x(structure, mouth_y)
    mw = 0.052 * head_h
    up = face.get("mouth", "short") not in ("down",)
    pen.quad((mx - mw, mouth_y), (mx, mouth_y + (0.018 if up else -0.018) * head_h),
             (mx + mw, mouth_y), 0.8 * pen_width(pen, 0.42))


def pen_width(pen: _Pen, factor: float) -> float:
    """Base stroke helper; ``unit`` is captured on the pen as ``base``."""
    return getattr(pen, "base", 1.0) * factor


def _draw_garment_details(pen, structure, masks, scale, features, skirt_top):
    head = structure["head"]
    top = head["top"]
    head_h = max(1.0, head["chin"][1] - top)
    waist_y = float(structure.get("waist_y", top + 2.0 * head_h))

    # Buttons: the blouse placket follows the torso axis.
    y0 = float(structure.get("shoulder_y", top + head_h)) + 0.30 * head_h
    y1 = max(y0 + 0.1 * head_h, skirt_top - 0.04 * head_h)
    base = getattr(pen, "base", 1.0)
    for i in range(4):
        by = y0 + (y1 - y0) * i / 3.0
        pen.circle(_axis_x(structure, by), by, 0.026 * head_h, 0.62 * base)

    cloth = masks.get("cloth", np.zeros((1, 1), bool))
    lower = np.zeros_like(cloth)
    row_min = int(max(0, waist_y / scale))
    lower[row_min:, :] = cloth[row_min:, :]
    lab, n_lab = label(lower, structure=CONNECT8)
    best_id, best_area = 0, 0
    for i in range(1, n_lab + 1):
        area = int((lab == i).sum())
        if area > best_area:
            best_id, best_area = i, area
    if best_id:
        skirt = lab == best_id
        ys, _xs = np.nonzero(skirt)
        sy0, sy1 = float(ys.min()), float(ys.max())
        span = sy1 - sy0
        top_span = _span_at(skirt, int(sy0 + 0.02 * span))
        hem_span = _span_at(skirt, int(sy1 - 0.03 * span))
        if top_span and hem_span:
            # Only the pleat fan: the skirt contour already carries the waist.
            for i in range(1, 7):
                t = i / 7.0
                x_top = (top_span[0] + (top_span[1] - top_span[0])
                         * (0.25 + 0.5 * t)) * scale
                x_hem = (hem_span[0] + (hem_span[1] - hem_span[0]) * t) * scale
                pen.open([(x_top, (sy0 + 0.015 * span) * scale),
                          (x_hem, (sy1 - 0.02 * span) * scale)], 0.36 * base)
    # Sailor collar stripes: two inset loops parallel to the collar edge.
    upper = np.zeros_like(cloth)
    upper[:row_min, :] = cloth[:row_min, :]
    for loop, closed in trace_loops(upper, scale,
                                    min_area=0.002 * lower.size * scale * scale):
        if not closed:
            continue
        pen.loop(_offset_loop(loop, 0.016 * head_h), 0.38 * base)
        pen.loop(_offset_loop(loop, 0.030 * head_h), 0.38 * base)


def render_lineart(structure: dict, masks: dict, features: dict,
                   width: int, height: int, unit: float, mask_scale: float,
                   skirt_top: float, ink=(74, 63, 54)) -> Image.Image:
    """Render an ink line-art RGBA layer from measured regions + descriptors."""
    scale = float(mask_scale)
    pen = _Pen(width, height, ink)
    base = max(1.8, 0.46 * unit)
    pen.base = base
    w_region = 1.0 * base
    w_hair = 0.78 * base

    order = [
        ("hair", w_hair, "hair"),
        ("white", w_region, "garment"),
        ("cloth", w_region, "garment"),
        ("skin", w_region, "skin"),
        ("accent", 0.85 * base, "accent"),
    ]
    shoulder_y = float(structure.get("shoulder_y", 0.0))
    for role, lw, _group in order:
        mask = masks.get(role)
        if mask is None or not mask.any():
            continue
        for loop, closed in trace_loops(mask, scale):
            # The face silhouette is rebuilt from the head axis, so skip skin
            # loops in the head region (they follow hair wisps).
            if role == "skin" and loop[:, 1].min() <= shoulder_y:
                continue
            # Drop thin leg slivers left by the canvas crop.
            if role == "skin" and loop[:, 1].max() - loop[:, 1].min() < 0.04 * height:
                continue
            if closed:
                pen.loop(loop, lw)
            else:
                pen.open(loop, lw)

    # Bows: an inner loop per bow lobe reads as a ribbon fold.
    accent = masks.get("accent")
    if accent is not None and accent.any():
        head_h = max(1.0, structure["head"]["chin"][1] - structure["head"]["top"])
        for loop, closed in trace_loops(accent, scale, min_area=4 * MIN_LOOP_AREA):
            if closed:
                pen.loop(_offset_loop(loop, 0.012 * head_h), 0.55 * base)

    skirt_top = float(skirt_top)
    _draw_garment_details(pen, structure, masks, scale, features, skirt_top)
    _draw_face(pen, structure, masks, scale, features)
    return pen.image()


def write_check(source_crop: Image.Image, lineart: Image.Image, out_path,
                max_h: int = 1100, wash: float = 1.0) -> None:
    """Line art on white, resized for review."""
    sw, sh = source_crop.size
    scale = min(1.0, max_h / float(sh))
    size = (max(1, int(round(sw * scale))), max(1, int(round(sh * scale))))
    white = Image.new("RGB", size, (255, 255, 255))
    if wash < 1.0:
        base = source_crop.resize(size, Image.LANCZOS).convert("RGB")
        white = Image.blend(base, white, wash)
    over = lineart.resize(size, Image.LANCZOS)
    Image.alpha_composite(white.convert("RGBA"), over).convert("RGB").save(out_path)


def write_overlay(source_crop: Image.Image, lineart: Image.Image, out_path,
                  max_h: int = 1100, wash: float = 0.55) -> None:
    """Line art over a washed source, to verify registration."""
    sw, sh = source_crop.size
    scale = min(1.0, max_h / float(sh))
    size = (max(1, int(round(sw * scale))), max(1, int(round(sh * scale))))
    base = source_crop.resize(size, Image.LANCZOS).convert("RGB")
    wash_img = Image.blend(base, Image.new("RGB", size, (255, 255, 255)), wash)
    over = lineart.resize(size, Image.LANCZOS)
    Image.alpha_composite(wash_img.convert("RGBA"), over).convert("RGB").save(out_path)
