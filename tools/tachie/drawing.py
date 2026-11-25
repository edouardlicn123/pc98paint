# -*- coding: utf-8 -*-
"""人物线稿与布料绘制语义；只处理掩码、几何和配置，不写文件。"""
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import (binary_closing, binary_dilation,
                           binary_erosion, binary_fill_holes,
                           distance_transform_edt, gaussian_filter, label)

from bust_sample2 import zhang_suen

import shading

OUTLINE, STRUCTURE, STRANDS = 1, 2, 3
CONNECT8 = np.ones((3, 3), dtype=bool)


@dataclass
class LineLayers:
    kind: np.ndarray
    protected: np.ndarray
    candidate: np.ndarray
    ink_core: np.ndarray
    contrast_edge: np.ndarray

    @property
    def mask(self):
        return self.kind > 0


@dataclass
class ClothLayers:
    base: np.ndarray
    form: np.ndarray
    fold: np.ndarray
    occlusion: np.ndarray
    highlight: np.ndarray
    protected: np.ndarray
    tones: dict
    surface: dict
    surface_tones: dict
    stats: dict

    def masks(self):
        return {name: getattr(self, name) for name in
                ("base", "form", "fold", "occlusion", "highlight")}


def despeckle_lines(mask, min_size=4, protected=None):
    """按八邻域清理孤立线点；含保护像素的连通线整段保留。"""
    mask = np.asarray(mask, dtype=bool)
    protected = (np.zeros(mask.shape, dtype=bool) if protected is None
                 else np.asarray(protected, dtype=bool) & mask)
    lab, _ = label(mask, structure=CONNECT8)
    sizes = np.bincount(lab.ravel())
    protected_components = np.bincount(
        lab.ravel(), weights=protected.ravel(), minlength=len(sizes)) > 0
    keep = (sizes >= min_size) | protected_components
    keep[0] = False
    return keep[lab]


def white_line_strict_mask(idx, fg, materials):
    """仅宽阔白衣内部过滤灰影；材质边界和人物轮廓附近保留原线稿。"""
    white_ids = [i for i, m in enumerate(materials) if m.get("role") == "white"]
    white = np.isin(idx, white_ids)
    if not white.any():
        return np.zeros_like(fg, dtype=bool)
    structure = ((idx >= 0) & ~white) | ~fg
    radius = max(2, round(idx.shape[1] * 20 / 257))
    return white & ~binary_dilation(structure, iterations=radius)


def _material_boundaries(idx):
    """求相邻像素材质接缝，包含真实暗结构与布料之间的接缝。"""
    boundary = np.zeros(idx.shape, dtype=bool)
    for axis in (0, 1):
        a = [slice(None), slice(None)]
        b = [slice(None), slice(None)]
        a[axis], b[axis] = slice(1, None), slice(None, -1)
        different = idx[tuple(a)] != idx[tuple(b)]
        boundary[tuple(a)] |= different
        boundary[tuple(b)] |= different
    return boundary


def build_line_layers(candidate, fg, material_idx=None, materials=None,
                      ink_core=None, contrast_edge=None, min_size=4,
                      protected=None):
    """构建互斥的 outline/structure/strands，并只做一次细化与清理。"""
    candidate = np.asarray(candidate, dtype=bool)
    zeros = np.zeros(candidate.shape, dtype=bool)
    ink_core = zeros if ink_core is None else np.asarray(ink_core, dtype=bool)
    contrast_edge = (zeros if contrast_edge is None
                     else np.asarray(contrast_edge, dtype=bool))
    outline = candidate & binary_dilation(~fg, iterations=1)

    strands = np.zeros(candidate.shape, dtype=bool)
    seams = np.zeros(candidate.shape, dtype=bool)
    if material_idx is not None and materials is not None:
        hair_ids = [i for i, m in enumerate(materials)
                    if m.get("role") == "hair"]
        hair = np.isin(material_idx, hair_ids)
        strands = (candidate & ~outline
                   & binary_dilation(hair, iterations=2))
        seams = candidate & binary_dilation(
            _material_boundaries(material_idx), iterations=1) & fg

    structure = candidate & ~outline & ~strands
    keep = despeckle_lines(
        zhang_suen(candidate), min_size=min_size,
        protected=outline | seams
        | (np.zeros(candidate.shape, bool) if protected is None else protected))

    # 清掉布料内部/白衣边缘的短排线；保留轮廓、接缝、受保护线，以及
    # 头发上的细分束线（参考画法本就靠发丝线条塑形）。
    if material_idx is not None and materials is not None:
        prot = (np.zeros(candidate.shape, bool) if protected is None
                else protected)
        cloth_ids = [i for i, m in enumerate(materials)
                     if m.get("role") in ("white", "cloth")]
        for ids, min_px in ((cloth_ids, 12),):
            if not ids:
                continue
            area = keep & np.isin(material_idx, ids) & ~(
                outline | seams | prot)
            lab_c, n_c = label(area, structure=CONNECT8)
            for j in range(1, n_c + 1):
                comp = lab_c == j
                if comp.sum() >= min_px:
                    continue
                # A short fragment that touches another kept line belongs to
                # a longer stroke; removing it would clip a legitimate line.
                ys_c, xs_c = np.where(comp)
                y0 = max(int(ys_c.min()) - 1, 0)
                y1 = min(int(ys_c.max()) + 2, candidate.shape[0])
                x0 = max(int(xs_c.min()) - 1, 0)
                x1 = min(int(xs_c.max()) + 2, candidate.shape[1])
                local = comp[y0:y1, x0:x1]
                rest = keep[y0:y1, x0:x1] & ~local
                if (binary_dilation(rest) & local).any():
                    continue
                keep &= ~comp

    # 回写时明确优先级，保证同一像素只属于一种线。
    kind = np.zeros(candidate.shape, dtype=np.uint8)
    kind[keep & structure] = STRUCTURE
    kind[keep & strands] = STRANDS
    kind[keep & outline] = OUTLINE
    final_protected = keep & (outline | seams
                              | (np.zeros(candidate.shape, bool)
                                 if protected is None else protected))
    return LineLayers(kind, final_protected, candidate.copy(),
                      ink_core.copy(), contrast_edge.copy())


def _hex_rgb(value):
    value = value.lstrip("#")
    return np.array([int(value[i:i + 2], 16) for i in (0, 2, 4)], np.float32)


def _bbox(mask):
    ys, xs = np.where(mask)
    if not len(ys):
        raise ValueError("绘制锚点所属材质不能为空")
    return float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())


def _points(values, bbox):
    x0, y0, x1, y1 = bbox
    points = np.asarray(values, dtype=np.float64)
    points = points.copy()
    points[:, 0] = x0 + points[:, 0] * (x1 - x0)
    points[:, 1] = y0 + points[:, 1] * (y1 - y0)
    return points


def _anchor_hit(mask, point):
    x, y = np.rint(point).astype(int)
    if not (0 <= y < mask.shape[0] and 0 <= x < mask.shape[1]):
        return False
    return bool(binary_dilation(mask, iterations=2)[y, x])


def _stroke(shape, points, width, kind="pinch", luminance=None,
            material_mask=None):
    """沿折线生成硬边暗面；radiate 由窄到宽，pinch 由宽到窄。"""
    points = np.asarray(points, dtype=np.float64)
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    best = np.full(shape, np.inf, dtype=np.float64)
    nearest = np.zeros(shape, dtype=np.float64)
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    total = max(float(lengths.sum()), 1e-6)
    offset = 0.0
    for p0, p1, seg_len in zip(points[:-1], points[1:], lengths):
        vector = p1 - p0
        denom = max(float(vector @ vector), 1e-6)
        t = np.clip(((xx - p0[0]) * vector[0]
                     + (yy - p0[1]) * vector[1]) / denom, 0.0, 1.0)
        px = p0[0] + t * vector[0]
        py = p0[1] + t * vector[1]
        dist = np.hypot(xx - px, yy - py)
        closer = dist < best
        best[closer] = dist[closer]
        nearest[closer] = (offset + t[closer] * seg_len) / total
        offset += float(seg_len)

    if kind == "radiate":
        profile = 0.25 + 0.75 * nearest
    elif kind in ("arc", "seam"):
        profile = np.ones(shape, dtype=np.float64)
    else:
        profile = 1.0 - 0.65 * nearest
    width_field = width * profile
    if luminance is not None and material_mask is not None and material_mask.any():
        median = float(np.median(luminance[material_mask]))
        width_field *= np.clip(1.0 + (median - luminance) * 2.0, 0.65, 1.35)
    return best <= np.maximum(0.5, width_field * 0.5)


def _clean_area(mask, min_px=2, min_length=2):
    out = np.zeros(mask.shape, dtype=bool)
    lab, n = label(mask, structure=CONNECT8)
    for i in range(1, n + 1):
        comp = lab == i
        ys, xs = np.where(comp)
        if len(xs) < min_px:
            continue
        if max(xs.max() - xs.min() + 1, ys.max() - ys.min() + 1) < min_length:
            continue
        out |= comp
    return out


def _tone(material, cfg, default):
    value = cfg.get("tone", default)
    return int(value) if value is not None else None


def _layer_edge_band(shape, over, under, width):
    """Take the seam from the solid core of over and expand into under.

    Eroding the occluder first removes lace/serration tips, whose every tooth
    would otherwise grow its own band and flood the neckline.
    """
    solid = binary_erosion(over, iterations=1)
    if not solid.any():
        solid = over
    distance = distance_transform_edt(~solid)
    return under & (distance <= max(float(width), 0.5))


def _keep_large(mask, min_px):
    """Keep only connected components of at least min_px pixels."""
    if not mask.any():
        return mask
    lab, n = label(mask)
    if n == 0:
        return mask
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    return np.isin(lab, np.where(sizes >= max(int(min_px), 1))[0])


def _despeckle_form(mid, deep, own, min_px):
    """Merge nearby shadow specks into coherent blocks, then drop components
    smaller than min_px.  Restores the v5->v8 rule (9px binary_closing +
    fill_holes + area floor) that directional_bands does not apply, so cloth
    volume shadow reads as clean masses instead of scattered dots.  `deep`
    stays a subset of `mid` to preserve the tone hierarchy."""
    st = np.ones((9, 9), bool)
    mid = binary_fill_holes(binary_closing(mid, structure=st))
    deep = binary_fill_holes(binary_closing(deep, structure=st))
    mid = _keep_large(mid, min_px) & own
    deep = _keep_large(deep, min_px) & own & mid
    return mid, deep


def _despeckle_occl(area, under, min_px, close=11):
    """Bridge nearby occlusion specks into a continuous band, then drop
    fragments smaller than min_px.  A serrated over-edge (e.g. sailor-collar
    V) projects a dashed seam onto the receiver; without bridging this reads
    as scattered dot shadow.  Closing bridges are clipped to `under` (the
    receiver material) so they survive -- clipping back to the original
    `area` would erase every bridge and leave the dashes intact."""
    st = np.ones((close, close), bool)
    merged = binary_fill_holes(binary_closing(area, structure=st))
    return _keep_large(merged, min_px) & under


def _seam_row(lum, y, lo, hi, ref, tol, torso):
    """Darkest local minimum of one row inside a side window.

    The painted arm/torso seam is a 1-2 px dip with bright pixels on both
    sides; folds qualify too, so the caller tracks continuity.  Candidates
    must sit on the blouse, which keeps the trace from wandering onto the
    arm once the sleeve ends.  Returns None when no line is dark enough.
    """
    best, near = None, []
    for x in range(int(lo) + 2, int(hi) - 2):
        if not (torso[y, x] or torso[y, x - 1] or torso[y, x + 1]):
            continue
        v = float(lum[y, x])
        if v > 0.90:
            continue
        side = max(lum[y, x - 3], lum[y, x + 3],
                   lum[y, x - 2], lum[y, x + 2])
        if side - v < 0.05:
            continue
        if best is None or v < best[0]:
            best = (v, float(x))
        if abs(x - ref) <= tol:
            near.append((v, float(x)))
    if near:
        return min(near)[1]
    return best[1] if best else None


def _trace_seam(lum, lo, hi, y_anchor, ref, y_lo, y_hi, torso, tol=6.0):
    """Track a seam line from the chest row outward in both directions."""
    x = _seam_row(lum, y_anchor, lo, hi, ref, 8.0, torso)
    if x is None:
        return []
    pts = {y_anchor: x}
    for step in (1, -1):
        px = x
        rng = range(y_anchor + step, y_hi + 1 if step > 0 else y_lo - 1, step)
        for y in rng:
            nxt = _seam_row(lum, y, lo, hi, px, tol, torso)
            if nxt is None:
                break
            px = nxt
            pts[y] = px
    return sorted(pts.items())


def _straighten_seam(points, trim=3.0):
    """Robust straight fit of traced seam points, rejecting fold outliers.

    A straight guide is stable across the chest and waist; the raw trace can
    jump onto sleeve folds for a few rows.
    """
    if len(points) < 4:
        return []
    ys = np.asarray([p[0] for p in points], dtype=float)
    xs = np.asarray([p[1] for p in points], dtype=float)
    keep = np.ones(len(ys), dtype=bool)
    slope = 0.0
    intercept = float(xs.mean())
    for _ in range(2):
        yy, xx = ys[keep], xs[keep]
        if len(yy) < 4:
            return []
        pair = [(b - a) / (d - c) for i, (c, a) in enumerate(zip(yy, xx))
                for d, b in list(zip(yy, xx))[i + 1:]]
        slope = float(np.median(pair))
        intercept = float(np.median(xx - slope * yy))
        keep = np.abs(xs - (intercept + slope * ys)) <= trim
    return [(int(y), float(intercept + slope * y))
            for y in range(int(ys.min()), int(ys.max()) + 1)]


def _clip_seam_rows(points, torso_mask):
    """Clamp every seam row to the blouse extent so the guide never leaves it.

    A straight fit extrapolates past the traced rows; without this clamp the
    lower end can land on the arm even though the fit itself was clean.
    """
    out = []
    for y, x in points:
        row = np.flatnonzero(torso_mask[y])
        if row.size < 2:
            continue
        out.append((y, float(np.clip(x, row.min() + 1.0, row.max() - 1.0))))
    return out


def _torso_limits(torso_mask, material_idx, materials, lum=None, anchor_y=None):
    """Return torso side limits and sway axis with the arms excluded.

    The blouse silhouette merges the sleeves into the torso component, so a
    bounding-box ratio alone cuts through the arm.  When the luminance map is
    available the painted arm/torso seam is traced per row and the band hugs
    that contour instead of a straight ratio inset.  The sway axis is a robust
    (Theil-Sen) fit of the silhouette midpoints, which stays upright even when
    one arm is occluded by hair.
    """
    ys, xs = np.nonzero(torso_mask)
    x0, x1 = float(xs.min()), float(xs.max())
    y0, y1 = float(ys.min()), float(ys.max())
    width = max(x1 - x0, 1.0)
    height = max(y1 - y0, 1.0)

    inset = 0.16
    ratio = {"left": x0 + inset * width, "right": x1 - inset * width,
             "source": "ratio"}

    seam_left, seam_right = [], []
    if lum is not None:
        y_a = int(round(anchor_y if anchor_y is not None
                        else y0 + 0.45 * height))
        # The arm/torso seam only exists around the ribcage; beyond it the
        # sleeve merges into the arm and the trace would wander onto the
        # limb.  Keep the guide near the chest row.
        span = 0.22 * height
        rows_lo = max(int(y0), int(round(y_a - span)))
        rows_hi = min(int(y1), int(round(y_a + span)))
        pad = 0.06 * width
        left = _trace_seam(lum, x0 + 0.04 * width, x0 + 0.44 * width,
                           y_a, ratio["left"], rows_lo, rows_hi, torso_mask)
        right = _trace_seam(lum, x1 - 0.44 * width, x1 - 0.04 * width,
                            y_a, ratio["right"], rows_lo, rows_hi, torso_mask)
        need = max(4, int(0.35 * (rows_hi - rows_lo)))
        if len(left) >= need and len(right) >= need:
            left = _clip_seam_rows(_straighten_seam(left), torso_mask)
            right = _clip_seam_rows(_straighten_seam(right), torso_mask)
        if left and right:
            left = [(y, float(np.clip(x, ratio["left"] - pad,
                                      ratio["left"] + 0.10 * width)))
                    for y, x in left]
            right = [(y, float(np.clip(x, ratio["right"] - 0.10 * width,
                                       ratio["right"] + pad)))
                     for y, x in right]
            if 0.25 * width < (np.median([p[1] for p in right])
                               - np.median([p[1] for p in left])):
                ratio = {**ratio, "source": "seam"}
                seam_left, seam_right = left, right

    mids = []
    low = int(y0 + 0.08 * height)
    high = int(y0 + 0.80 * height) + 1
    for y in range(low, high, 2):
        row = np.flatnonzero(torso_mask[y])
        if row.size == 0 or (row.max() - row.min()) < 0.5 * width:
            continue
        mids.append((float(y), float(row.min() + row.max()) * 0.5))
    slope = 0.0
    intercept = float(xs.mean())
    if len(mids) >= 6:
        pts = np.asarray(mids)
        pair = [(b[1] - a[1]) / (b[0] - a[0])
                for i, a in enumerate(pts) for b in pts[i + 1:]]
        slope = float(np.clip(np.median(pair), -0.35, 0.35))
        intercept = float(np.median(pts[:, 1] - slope * pts[:, 0]))
    return {**ratio, "slope": slope, "intercept": intercept,
            "width": width, "height": height,
            "seam_left": seam_left, "seam_right": seam_right}


def _bust_geometry(white_mask, body, material_idx, materials, lum=None):
    """Locate bust lobes from shoulder/waist anatomy, not blouse height."""
    bust = (body or {}).get("bust") or {}
    size = int(bust.get("size", 0) or 0)
    if size < 1 or not white_mask.any():
        return {"size": size, "lobes": []}
    lab_w, n_w = label(white_mask)
    sizes_w = np.bincount(lab_w.ravel())
    sizes_w[0] = 0
    torso_mask = lab_w == int(sizes_w.argmax())
    x0, y0, x1, y1 = _bbox(torso_mask)
    width = max(x1 - x0, 1.0)
    height = max(y1 - y0, 1.0)
    shoulder_y = y0
    waist_y = y0 + 0.78 * height
    near_white = binary_dilation(torso_mask, iterations=4)
    torso_area = int(torso_mask.sum())
    for i, material in enumerate(materials):
        if material.get("role") != "cloth":
            continue
        cloth = material_idx == i
        lab_c, n_c = label(cloth)
        for component_id in range(1, n_c + 1):
            component = lab_c == component_id
            area = int(component.sum())
            # Skip background-scale regions that only graze the torso.
            if area > 3 * torso_area:
                continue
            if not (component & near_white).any():
                continue
            top = float(np.where(component)[0].min())
            if y0 - 0.10 * height <= top < y0 + 0.35 * height:
                shoulder_y = min(shoulder_y, top)
            elif top > y0 + 0.55 * height:
                waist_y = min(waist_y, top)
    waist_y = max(waist_y, shoulder_y + 0.45 * (y1 - shoulder_y))
    torso = (body or {}).get("torso") or {}
    bust_ratio = 0.76 if torso.get("pose") == "lean_forward" else 0.57
    center_y = shoulder_y + bust_ratio * (waist_y - shoulder_y)

    frame = _torso_limits(torso_mask, material_idx, materials, lum,
                          anchor_y=center_y)
    lean = float(torso.get("lean", 0.0) or 0.0)

    # Head axis: one vertical guide from the top of the head to the shoulders.
    head_x, head_top = None, None
    skin_ids = [i for i, m in enumerate(materials)
                if m.get("role") == "skin"]
    if skin_ids:
        skin = np.isin(material_idx, skin_ids)
        head = skin[:int(shoulder_y)]
        if head.sum() >= 50:
            head_x = float(np.nonzero(head)[1].mean())
            rows = np.nonzero(head.any(axis=1))[0]
            head_top = float(rows.min()) if rows.size else float(shoulder_y)

    def band_at(y):
        if frame["seam_left"]:
            left = np.interp(y, [p[0] for p in frame["seam_left"]],
                             [p[1] for p in frame["seam_left"]])
            right = np.interp(y, [p[0] for p in frame["seam_right"]],
                              [p[1] for p in frame["seam_right"]])
            return float(left), float(right)
        return frame["left"], frame["right"]

    left_c, right_c = band_at(center_y)
    torso_w = max(right_c - left_c, 4.0)
    margin = max(1.5, 0.03 * torso_w)
    if frame["seam_left"]:
        # The traced seam midline is the body axis; the face midline sits a
        # few pixels right of it on a contrapposto pose.
        anchor_x = 0.5 * (left_c + right_c)
        center_source = "seam"
    else:
        # Without a seam, the chest hangs under the head, so the face midline
        # is the stable anchor; silhouette midpoints are biased by hair.
        if head_x is not None:
            anchor_x = head_x
            center_source = "face"
        else:
            anchor_x = frame["intercept"] + frame["slope"] * center_y
            center_source = "silhouette"
    center_x = anchor_x + lean * torso_w * 0.25
    center_x = float(np.clip(center_x, left_c + margin, right_c - margin))

    separation = float(np.clip(bust.get("separation", 0.42), 0.2, 0.95))
    sep_px = min(separation * torso_w, max(0.0, torso_w - 2.0 * margin))
    d = sep_px * 0.5
    # The band tilts with the sway axis, so the chest line runs perpendicular
    # to the body and the lobe on the lower side of the lean rides lower.
    # Equal cy values are what made the pair look level on a tilted torso.
    slope = float(frame["slope"])
    norm = float(np.hypot(1.0, slope))
    ux, uy = 1.0 / norm, -slope / norm
    centers = [(center_x - d * ux, center_y - d * uy),
               (center_x + d * ux, center_y + d * uy)]
    # Fill the band out to the seam so each lobe reads as a body part rather
    # than a small stamp floating inside the torso.
    gap = max(1.2, 0.015 * torso_w)
    room = min(min(cx - band_at(cy)[0], band_at(cy)[1] - cx)
               for cx, cy in centers)
    rx = max(3.0, (room - gap) * min(1.0, 0.85 + 0.075 * size))
    ry = max(4.0, rx * (0.80 + 0.04 * size))
    half = 0.5 * torso_w
    lobes = [(cx, cy, rx, ry) for cx, cy in centers]
    return {
        "size": size, "lobes": lobes,
        "shoulder_y": round(shoulder_y, 2), "waist_y": round(waist_y, 2),
        "center_y": round(center_y, 2), "torso_ratio": bust_ratio,
        "center_x": round(center_x, 2),
        "torso_left": round(center_x - half, 2),
        "torso_right": round(center_x + half, 2),
        "torso_width": round(torso_w, 2),
        "sway_deg": round(float(np.degrees(np.arctan(frame["slope"]))), 2),
        "slope": float(frame["slope"]),
        "seam_left": frame["seam_left"],
        "seam_right": frame["seam_right"],
        "arm_source": frame["source"],
        "center_source": center_source,
        "head_x": None if head_x is None else round(head_x, 2),
        "head_top": None if head_top is None else round(head_top, 2),
    }


def body_guide(material_idx, materials, body, lum):
    """Measure the figure once, before any shading pass.

    Returns the head axis, shoulder/waist heights, torso band and bust lobes.
    Later passes shade against this same figure instead of re-deriving the
    body per garment, so the anatomy is fixed before colours are laid down.
    """
    white_ids = [i for i, m in enumerate(materials)
                 if m.get("role") == "white"]
    if not body or not white_ids:
        return {"size": 0, "lobes": [], "mask_id": None}
    mask_id = max(white_ids, key=lambda i: int((material_idx == i).sum()))
    guide = _bust_geometry(material_idx == mask_id, body, material_idx,
                           materials, lum)
    guide["mask_id"] = mask_id
    return guide


def _head_occluder(material_idx, materials, guide):
    """The head mass above the shoulder line, clipped to the skull axis.

    Hair spreads far wider than the skull; projecting every lock produced a
    gray band running parallel to the strands on the lit side (v10.2 ②).  The
    skull width comes from the head skin so the projection keeps a head-scale
    silhouette instead of the whole hair mass.
    """
    guide = guide or {}
    shoulder_y = guide.get("shoulder_y")
    if shoulder_y is None:
        return None
    soft = [i for i, m in enumerate(materials)
            if m.get("role") in ("hair", "skin")]
    if not soft:
        return None
    rows = np.arange(material_idx.shape[0])[:, None]
    cols = np.arange(material_idx.shape[1])[None, :]
    above = rows < float(shoulder_y)
    mass = np.isin(material_idx, soft) & above
    if not mass.any():
        return None
    skin_ids = [i for i, m in enumerate(materials) if m.get("role") == "skin"]
    skin = np.isin(material_idx, skin_ids) & above
    head_x, head_top = guide.get("head_x"), guide.get("head_top")
    if skin.sum() >= 50:
        xs = np.nonzero(skin)[1]
        head_w = float(xs.max() - xs.min() + 1)
        if head_x is None:
            head_x = float(xs.mean())
    else:
        xs = np.nonzero(mass)[1]
        head_w = 0.5 * float(xs.max() - xs.min() + 1)
        if head_x is None:
            head_x = float(xs.mean())
    if head_top is None:
        head_top = float(np.nonzero(mass)[0].min())
    half = 0.5 * head_w
    mass &= ((cols >= head_x - half) & (cols <= head_x + half)
             & (rows >= head_top))
    return mass if mass.any() else None


def _head_cast_depth(head, guide):
    """Projection length derived from head width and shoulder span.

    The fixed W/32 depth was unrelated to anatomy; a low key light throws a
    shadow about one head radius long, stretched slightly by the shoulders.
    """
    xs = np.nonzero(head)[1]
    head_w = float(xs.max() - xs.min() + 1)
    torso_w = float((guide or {}).get("torso_width") or head_w)
    return float(np.clip(0.30 * head_w + 0.06 * torso_w, 4.0, 0.8 * head_w))


def _run_widths(mask):
    """Width of the horizontal run containing each pixel (0 outside)."""
    width = mask.shape[1]
    cols = np.arange(width)[None, :]
    left = np.zeros_like(mask)
    left[:, 0] = mask[:, 0]
    left[:, 1:] = mask[:, 1:] & ~mask[:, :-1]
    right = np.zeros_like(mask)
    right[:, -1] = mask[:, -1]
    right[:, :-1] = mask[:, :-1] & ~mask[:, 1:]
    start = np.maximum.accumulate(np.where(left, cols, 0), axis=1)
    end = np.minimum.accumulate(
        np.where(right, cols, width)[:, ::-1], axis=1)[:, ::-1]
    return end - start


def _form_field_break(field, base, material_idx, min_run=12):
    """Max field step at a material break whose cross-section is unchanged."""
    solid = shading.silhouette(base)
    widths = _run_widths(solid)
    jump = np.abs(np.diff(field, axis=0))
    breaks = (base[:-1] & base[1:]
              & (material_idx[:-1] != material_idx[1:])
              & (np.abs(widths[:-1] - widths[1:]) <= 1)
              & (widths[:-1] >= min_run))
    return float(jump[breaks].max()) if breaks.any() else 0.0


def _bust_form(mask, light, body, material_idx, materials, lum=None,
               guide=None, field=None):
    """Merge torso, bust spheres and their cast shadows into one field."""
    model = guide if guide else _bust_geometry(
        mask, body, material_idx, materials, lum)
    field = (np.array(field, dtype=np.float64) if field is not None
             else shading.cylindrical_field(mask, light))
    yy, xx = np.mgrid[0:mask.shape[0], 0:mask.shape[1]]
    source = np.zeros_like(mask)
    lower_edge = np.zeros_like(mask)
    size = model["size"]
    for cx, cy, rx, ry in model["lobes"]:
        lobe_field = shading.ellipsoid_field(
            mask, cx, cy, rx, ry, light, terminator=0.30 + 0.08 * size)
        field = np.maximum(field, lobe_field)
        ellipse = (((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2) <= 1.0
        source |= ellipse & mask
        lower_edge |= ellipse & mask & (yy >= cy + 0.25 * ry)
    if source.any():
        mean_ry = float(np.mean([lobe[3] for lobe in model["lobes"]]))
        near = shading.cast_shadow(source, mask, light, depth=0.55 * mean_ry)
        far = shading.cast_shadow(source, mask, light, depth=1.15 * mean_ry)
        contact = shading.cast_shadow(
            lower_edge, mask, light, depth=max(2.0, 0.12 * mean_ry))
        # Two displaced projections form the soft abdominal penumbra; the
        # short under-bust projection is the hard contact/umbra edge.
        field[near | far] = np.maximum(field[near | far], 0.46)
        field[contact] = np.maximum(field[contact], 0.86)
        model["cast_pixels"] = int((near | far).sum())
        model["contact_pixels"] = int(contact.sum())
    mid, deep, _ = shading.field_bands(
        field, mask, thresholds=(0.35, 0.82), min_px=8)
    model["form_pixels"] = int(mid.sum())
    model["deep_pixels"] = int(deep.sum())
    return mid, deep, model


def build_cloth_layers(rgb, fg, material_idx, materials, config=None, body=None):
    """构建 base/form/fold/occlusion/highlight，并返回材质表面覆盖层。"""
    config = config or {}
    shape = fg.shape
    empty = np.zeros(shape, dtype=bool)
    roles = [m.get("role", "flat") for m in materials]
    base = np.isin(material_idx, [i for i, r in enumerate(roles)
                                  if r in ("white", "cloth")])
    form = np.zeros(shape, dtype=bool)
    fold = np.zeros(shape, dtype=bool)
    occlusion = np.zeros(shape, dtype=bool)
    highlight = np.zeros(shape, dtype=bool)
    tones = {name: np.full(shape, -1, dtype=np.int16) for name in
             ("form", "fold", "occlusion", "highlight")}
    stats = {"folds": [], "occlusions": [], "highlights": [], "surface": {}}
    lum = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1]
           + 0.114 * rgb[..., 2]) / 255.0
    smooth_lum = gaussian_filter(lum, 2.0)
    light = shading.light_vector(config.get("light", "upper-left"))
    # Anatomy first: the head axis, torso band and bust guide are measured
    # before any garment shading, so every material shares one figure.
    guide = body_guide(material_idx, materials, body, lum)
    stats["body"] = guide

    # One body-space field for the whole garment silhouette.  Cross-sections
    # must not restart at a material boundary: a short skirt run under the
    # blouse hem would otherwise become a bright beige wedge (v10.2 ③).
    body_field = shading.cylindrical_field(base, light)
    stats["form_field_break"] = _form_field_break(
        body_field, base, material_idx)

    # Body-space volume field: horizontal cylinder sections remain continuous
    # through material holes, then the field is clipped to each garment.
    groups = {}
    for i, material in enumerate(materials):
        if material.get("role") == "cloth":
            groups.setdefault(material.get("group") or material["id"], []).append(i)
    for members in groups.values():
        union = np.isin(material_idx, members)
        if not union.any():
            continue
        mid, deep, _ = shading.field_bands(
            body_field, union, thresholds=(0.35, 0.82), min_px=20)
        for i in members:
            own = material_idx == i
            m_mid, m_deep = _despeckle_form(
                own & mid, own & deep, own,
                max(20, int(own.sum() * 0.02)))
            form |= m_mid | m_deep
            last = len(materials[i].get("refs", [])) - 1
            tones["form"][m_mid] = min(1, last)
            tones["form"][m_deep] = min(2, last)

    white_ids = [i for i, m in enumerate(materials) if m.get("role") == "white"]
    body_white_i = guide.get("mask_id")
    for i in white_ids:
        material = materials[i]
        mask = material_idx == i
        if not mask.any():
            continue
        if i == body_white_i:
            mid, deep, _ = _bust_form(
                mask, light, body, material_idx, materials, lum, guide,
                field=body_field)
        else:
            mid, deep, _ = shading.field_bands(
                body_field, mask, thresholds=(0.35, 0.82), min_px=40)
        mid, deep = _despeckle_form(
            mid, deep, mask, max(40, int(mask.sum() * 0.02)))
        form |= mid | deep
        last = len(material.get("refs", [])) - 1
        tones["form"][mid] = min(1, last)
        tones["form"][deep] = min(2, last)

    by_id = {m["id"]: i for i, m in enumerate(materials)}
    for cfg in config.get("folds", []):
        i = by_id[cfg["material"]]
        material = materials[i]
        mask = material_idx == i
        values = cfg.get("path") or [cfg["from"], cfg["to"]]
        points = _points(values, _bbox(mask))
        candidate = _stroke(shape, points, float(cfg.get("width", 2)),
                            cfg.get("kind", "pinch"), smooth_lum, mask)
        area = _clean_area(candidate & mask)
        tone = _tone(material, cfg, len(material.get("refs", [])) - 1)
        fold |= area
        tones["fold"][area] = tone
        stats["folds"].append({
            "material": material["id"], "kind": cfg.get("kind", "pinch"),
            "anchor_hit": _anchor_hit(mask, points[0]),
            "pixels": int(area.sum()), "tone": tone,
        })

    for cfg in config.get("occlusions", []):
        under_i = by_id[cfg["under"]]
        over_i = by_id[cfg["over"]]
        under = material_idx == under_i
        over = material_idx == over_i
        width = float(cfg.get("width", 2))
        if cfg.get("derive") == "layer_edge":
            candidate = _layer_edge_band(shape, over, under, width)
        elif cfg.get("path"):
            points = _points(cfg["path"], _bbox(under))
            candidate = _stroke(shape, points, width, "seam")
        else:
            candidate = binary_dilation(
                over, iterations=max(1, int(round(width))))
        area = _clean_area(candidate & under)
        # De-speckle the projected seam (see _despeckle_occl): bridge dashed
        # collar/cuff projections into clean bands and drop isolated specks.
        area = _despeckle_occl(
            area, under, max(20, int(under.sum() * 0.01)), close=11)
        tone = _tone(materials[under_i], cfg,
                     len(materials[under_i].get("refs", [])) - 1)
        occlusion |= area
        tones["occlusion"][area] = tone
        stats["occlusions"].append({
            "over": cfg["over"], "under": cfg["under"],
            "derive": cfg.get("derive") or ("path" if cfg.get("path")
                                            else "dilate"),
            "pixels": int(area.sum()), "tone": tone,
        })

    # The head is the only occluder above the shoulders.  Hair locks beside the
    # face belong to the head mass but must not project a band down the torso;
    # the cast is clipped to the skull axis and to the back-lit half so it can
    # only land on the collar and the upper chest (refs/proportions 02/08/14/
    # 18/19).  The collar→blouse chain is still owned by the config occlusions
    # above, so the head layer is not projected a second time.
    head = _head_occluder(material_idx, materials, guide)
    receiver_ids = set(white_ids)
    for members in groups.values():
        receiver_ids.update(members)
    if head is not None and receiver_ids:
        depth = _head_cast_depth(head, guide)
        cast = shading.cast_shadow(head, base, light, depth=depth)
        yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
        center_x = float(guide["center_x"])
        shoulder_y = float(guide["shoulder_y"])
        back_lit = ((xx >= center_x) & (yy >= shoulder_y - 1.0))
        # 1px contact umbra next to the head, soft mid tone further out.
        contact = (binary_dilation(head, iterations=1) & base & back_lit)
        cast &= back_lit
        for i in sorted(receiver_ids):
            under = material_idx == i
            area = _despeckle_occl(
                cast & under, under, max(12, int(under.sum() * 0.005)), close=5)
            if not area.any():
                continue
            ours = contact & area
            last = len(materials[i].get("refs", [])) - 1
            occlusion |= area
            tones["occlusion"][area] = min(1, last)
            tones["occlusion"][ours] = min(2, last)
            stats["occlusions"].append({
                "over": "head", "under": materials[i]["id"],
                "derive": "head_cast", "depth": round(depth, 2),
                "pixels": int(area.sum()),
                "contact_pixels": int(ours.sum()), "tone": min(1, last),
            })

    for cfg in config.get("highlights", []):
        i = by_id[cfg["material"]]
        mask = material_idx == i
        tone = _tone(materials[i], cfg, None)
        if tone is None:
            stats["highlights"].append({"material": cfg["material"],
                                        "pixels": 0, "skipped": "no_highlight_tone"})
            continue
        values = cfg.get("path") or [cfg["from"], cfg["to"]]
        points = _points(values, _bbox(mask))
        candidate = _stroke(shape, points, float(cfg.get("width", 2)), "arc")
        bright = smooth_lum >= float(np.median(smooth_lum[mask]))
        area = _clean_area(candidate & mask & bright)
        highlight |= area
        tones["highlight"][area] = tone
        stats["highlights"].append({"material": cfg["material"],
                                    "pixels": int(area.sum()), "tone": tone})

    # 白衣紧贴脸/颈/发的边缘保持白色；灰绿贴脸会被误读成脸部阴影。
    # Only the volume band is cleared here.  The contact shadow belongs to the
    # occlusion layer and must survive, otherwise a white gap appears between
    # the head and its cast shadow (v10.2 ②).
    white_ids = [i for i, m in enumerate(materials)
                 if m.get("role") == "white"]
    soft_ids = [i for i, m in enumerate(materials)
                if m.get("role") in ("skin", "hair")]
    if white_ids and soft_ids:
        near_soft = binary_dilation(np.isin(material_idx, soft_ids),
                                    iterations=3)
        white_edge = np.isin(material_idx, white_ids) & near_soft
        form &= ~white_edge

    surface, surface_tones = _build_surfaces(
        materials, by_id, material_idx, fold, config.get("materials", {}),
        smooth_lum, stats)
    protected = fold | occlusion | highlight
    for mask in surface.values():
        protected |= mask
    stats["layers"] = {name: int(mask.sum()) for name, mask in
                       (("base", base), ("form", form), ("fold", fold),
                        ("occlusion", occlusion), ("highlight", highlight))}
    return ClothLayers(base, form, fold, occlusion, highlight, protected,
                       tones, surface, surface_tones, stats)


def _build_surfaces(materials, by_id, material_idx, fold, configs,
                    smooth_lum, stats):
    """plain/plaid/fur/swimwear 共用既有材质 refs，不增加颜色。"""
    surfaces, tone_maps = {}, {}
    yy, xx = np.mgrid[0:material_idx.shape[0], 0:material_idx.shape[1]]
    for material_id, cfg in configs.items():
        kind = cfg.get("surface", "plain")
        if kind == "plain":
            continue
        i = by_id[material_id]
        material = materials[i]
        mask = material_idx == i
        tone_map = np.full(mask.shape, -1, dtype=np.int16)
        overlay = np.zeros(mask.shape, dtype=bool)
        if kind == "plaid":
            spacing = cfg.get("spacing", 6)
            sx, sy = ((spacing, spacing) if isinstance(spacing, int)
                      else (spacing[0], spacing[-1]))
            axis = np.asarray(cfg.get("axis", [1, 0]), dtype=np.float64)
            axis /= max(float(np.linalg.norm(axis)), 1e-6)
            cross = np.asarray(cfg.get("cross_axis", [-axis[1], axis[0]]))
            warp = gaussian_filter(fold.astype(np.float64), 2.0) * sx * 0.75
            line_width = float(cfg.get("line_width", 1))
            primary = ((xx * axis[0] + yy * axis[1] + warp) % sx) < line_width
            secondary = ((xx * cross[0] + yy * cross[1] - warp) % sy) < line_width
            tones = cfg.get("tones", [len(material.get("refs", [])) - 1])
            overlay = mask & (primary | secondary)
            tone_map[mask & primary] = tones[0]
            if cfg.get("cross", True):
                tone_map[mask & secondary] = tones[min(1, len(tones) - 1)]
            else:
                overlay = mask & primary
        elif kind == "fur":
            edge_width = max(1, int(cfg.get("edge_width", 2)))
            edge = mask & (distance_transform_edt(mask) <= edge_width)
            teeth = (((xx + 2 * yy) % 5) < 2) | ((xx - yy) % 7 == 0)
            overlay = edge & teeth
            tone_map[overlay] = cfg.get("tone", len(material.get("refs", [])) - 1)
        elif kind == "swimwear":
            bbox = _bbox(mask)
            for arc in cfg.get("arcs", []):
                tone = arc.get("tone")
                if tone is None:
                    continue
                points = _points(arc["path"], bbox)
                candidate = _stroke(mask.shape, points,
                                    float(arc.get("width", 2)), "arc")
                # 配置弧线限定位置，源图亮脊负责裁掉明显背光段。
                bright = mask & (smooth_lum >= float(np.median(smooth_lum[mask])))
                area = _clean_area(candidate & bright)
                overlay |= area
                tone_map[area] = tone
        surfaces[material_id] = overlay
        tone_maps[material_id] = tone_map
        stats["surface"][material_id] = {"surface": kind,
                                         "pixels": int(overlay.sum())}
    return surfaces, tone_maps
