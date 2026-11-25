# -*- coding: utf-8 -*-
"""Body structure: a *posed* skeleton, not an axis-aligned box.

All functions here work on a *detection resolution* (typically 720 px tall) and
return coordinates in that same resolution.  ``scale_structure`` maps the result
onto the working canvas.

The torso follows the sway axis measured by ``drawing.body_guide``: shoulder and
waist lines are perpendicular to that axis and the head axis leans with it.
Limbs are always complete (shoulder-elbow-wrist, hip-knee-ankle); segments hidden
by clothes or the crop are marked ``estimated`` and rendered dashed instead of
being dropped.
"""
from __future__ import annotations

import copy
import math

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import (binary_closing, binary_fill_holes,
                           distance_transform_edt, label)

from bust_sample2 import zhang_suen

COLORS = {
    "frame": (229, 57, 53, 235),
    "bust": (253, 216, 53, 235),
    "arm": (251, 140, 0, 235),
    "leg": (67, 160, 71, 235),
    "hand": (0, 229, 255, 150),
}


def _neighbors(y, x):
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                yield y + dy, x + dx


def _degree(skel: np.ndarray) -> np.ndarray:
    p = np.pad(skel.astype(np.uint8), 1)
    total = np.zeros(skel.shape, np.uint8)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                total += p[1 + dy:1 + dy + skel.shape[0],
                           1 + dx:1 + dx + skel.shape[1]]
    return total * skel.astype(np.uint8)


def _trace(coords):
    pts = set(coords)
    if len(pts) <= 1:
        return list(pts)

    def nbrs(p):
        return [q for q in _neighbors(*p) if q in pts]

    ends = [p for p in coords if len(nbrs(p)) <= 1]
    start = ends[0] if ends else coords[0]
    path = [start]
    prev, cur = None, start
    while True:
        nxt = [q for q in nbrs(cur) if q != prev]
        if not nxt:
            break
        prev, cur = cur, nxt[0]
        if cur == start or cur in path:
            break
        path.append(cur)
    return path


def _segments(skel: np.ndarray, edt: np.ndarray):
    deg = _degree(skel)
    nodes = skel & ((deg == 1) | (deg >= 3))
    paths = skel & ~nodes
    lab, n = label(paths, structure=np.ones((3, 3), bool))
    out = []
    for i in range(1, n + 1):
        ys, xs = np.where(lab == i)
        coords = list(zip(ys.tolist(), xs.tolist()))
        if len(coords) < 6:
            continue
        path = _trace(coords)
        if len(path) < 3:
            continue
        length = 0.0
        for (y0, x0), (y1, x1) in zip(path, path[1:]):
            length += math.hypot(y1 - y0, x1 - x0)
        w = [2.0 * edt[y, x] for y, x in path]
        out.append({
            "path": path,
            "length": length,
            "width": float(np.median(w)),
            "mid": path[len(path) // 2],
        })
    return out


def _snap(mask, nearest, y, x, max_dist=None):
    iy, ix = nearest
    yy = int(np.clip(round(y), 0, mask.shape[0] - 1))
    xx = int(np.clip(round(x), 0, mask.shape[1] - 1))
    if mask[yy, xx]:
        return float(yy), float(xx)
    sy, sx = float(iy[yy, xx]), float(ix[yy, xx])
    if max_dist is not None and math.hypot(sy - yy, sx - xx) > max_dist:
        return float(yy), float(xx)
    return sy, sx


def _width(edt, y, x, radius):
    h, w = edt.shape
    y0, y1 = max(0, int(y) - radius), min(h, int(y) + radius + 1)
    x0, x1 = max(0, int(x) - radius), min(w, int(x) + radius + 1)
    if y0 >= y1 or x0 >= x1:
        return 2.0
    vals = edt[y0:y1, x0:x1]
    vals = vals[vals > 0]
    if not vals.size:
        return 2.0
    return float(2.0 * np.percentile(vals, 75))


def _pick_side(segs, center_x, lo, hi, min_len, outer):
    best = {"left": None, "right": None}
    for s in segs:
        if s["length"] < min_len:
            continue
        ys = [p[0] for p in s["path"]]
        if max(ys) < lo or min(ys) > hi:
            continue
        if outer and abs(s["mid"][1] - center_x) < outer:
            continue
        side = "left" if s["mid"][1] < center_x else "right"
        if best[side] is None or s["length"] > best[side]["length"]:
            best[side] = s
    return best


def _axis_x(guide, y):
    """Body axis: leans with the measured sway, pivoting on the chest centre."""
    slope = float(guide.get("slope") or 0.0)
    pivot = guide.get("center_y", guide["shoulder_y"])
    return guide["center_x"] + slope * (y - pivot)


def apply_proportions(guide: dict, proportions: dict) -> dict:
    """Attach character-proportion measurements to the guide.

    ``heads`` (head-to-body ratio) turns the measured head height into a full
    body height, which then fixes the knee/ankle heights even when the crop
    cuts them off.  ``head_skin_w`` is the measured face width, used for the
    head circle.
    """
    heads = float((proportions or {}).get("heads", 6.5) or 6.5)
    head_top = float(guide.get("head_top") or 0.0)
    chin = guide.get("head_chin")
    head_h = max(8.0, float(chin[1]) - head_top) if chin else max(
        8.0, (float(guide["shoulder_y"]) - head_top) * 0.9)
    guide["head_top"] = head_top
    guide["head_h"] = head_h
    guide["full_h"] = head_h * heads
    return guide


def _shoulder_anchor(side, guide, height):
    """Glenohumeral joint below the shoulder seam and inside the sleeve."""
    sy = guide["shoulder_y"]
    sign = -1.0 if side == "left" else 1.0
    # The joint span is narrower than the clothed shoulder silhouette.
    half_span = 0.28 * guide["head_h"] * guide.get("shoulder_ratio", 1.4)
    base_y = sy + 0.07 * height
    center_x = _axis_x(guide, base_y)
    x = center_x + sign * half_span
    slope = float(guide.get("slope") or 0.0)
    y = base_y - 0.5 * slope * (x - center_x)
    return y, x


def _hidden_wrist(side, guide, height, min_y=None):
    """Hands clasped behind the pelvis, beyond any visible forearm skin."""
    sign = -1.0 if side == "left" else 1.0
    waist = guide.get("anatomy_waist_y", guide["waist_y"])
    wy = max(waist + 0.08 * height, min_y or 0.0)
    return wy, _axis_x(guide, wy) + sign * 0.06 * guide["torso_width"]


def _hand_near(skin_mask, wrist, height):
    r = max(4, int(height * 0.035))
    y0 = max(0, int(wrist[0]) - r)
    y1 = min(skin_mask.shape[0], int(wrist[0]) + r + 1)
    x0 = max(0, int(wrist[1]) - r)
    x1 = min(skin_mask.shape[1], int(wrist[1]) + r + 1)
    area = int(skin_mask[y0:y1, x0:x1].sum())
    if area < max(24, int(height * height * 0.0012)):
        return None
    return {"cx": float(wrist[1]), "cy": float(wrist[0]),
            "r": float(max(3.0, math.sqrt(area / math.pi)))}


def _elbow_from_skin(side, guide, skin_mask, height):
    """Place the elbow just above the measured visible forearm component."""
    shoulder = guide["shoulder_y"]
    waist = guide.get("anatomy_waist_y", guide["waist_y"])
    center = guide["center_x"]
    tw = guide["torso_width"]
    lab, n = label(skin_mask, structure=np.ones((3, 3), bool))
    best = None
    for i in range(1, n + 1):
        ys, xs = np.where(lab == i)
        if len(ys) < max(40, int(height * height * 0.0005)):
            continue
        top = int(ys.min())
        if top < shoulder + 0.22 * height or top > waist + 0.12 * height:
            continue
        cx = float(np.median(xs))
        if (cx < center) != (side == "left") or abs(cx - center) < 0.30 * tw:
            continue
        if best is None or len(ys) > best[0]:
            best = (len(ys), ys, xs)
    if best is None:
        return None
    _, ys, xs = best
    top, bottom = int(ys.min()), int(ys.max())
    band_size = max(2, int(0.03 * height))
    top_band = ys <= top + band_size
    bottom_band = ys >= bottom - band_size
    # The elbow ring belongs inside the measured forearm skin.  Pinning it to
    # the hem (sleeve edge) puts the joint above the arm the viewer can see.
    elbow_y = float(top + 0.40 * max(1, bottom - top))
    elbow_band = (ys >= elbow_y - band_size) & (ys <= elbow_y + band_size)
    elbow_x = float(np.median(xs[elbow_band])) if elbow_band.any() \
        else float(np.median(xs[top_band]))
    return {
        "elbow": (elbow_y, elbow_x),
        "visible_from": [float(np.median(xs[top_band])), float(top)],
        "visible_to": [float(np.median(xs[bottom_band])), float(bottom)],
    }


def _arm(side, guide, edt, nearest, mask, skin_mask, height, seg):
    sy, sx = _shoulder_anchor(side, guide, height)
    limit = height * 0.06
    shoulder = _snap(mask, nearest, sy, sx, max_dist=limit)
    sign = -1.0 if side == "left" else 1.0
    source = "fallback"
    elbow = None
    visible_from = visible_to = None
    skin_elbow = _elbow_from_skin(side, guide, skin_mask, height)
    if skin_elbow is not None:
        elbow = _snap(mask, nearest, *skin_elbow["elbow"], max_dist=limit)
        visible_from = skin_elbow["visible_from"]
        visible_to = skin_elbow["visible_to"]
        source = "forearm"
    wrist = None
    if seg is not None:
        path = seg["path"]
        fwd = path if math.hypot(path[0][0] - sy, path[0][1] - sx) <= \
            math.hypot(path[-1][0] - sy, path[-1][1] - sx) else path[::-1]
        n = len(fwd)
        if elbow is None:
            elbow = _snap(mask, nearest,
                          *fwd[min(n - 1, max(1, int(round(n * 0.55))))],
                          max_dist=limit)
        wrist = _snap(mask, nearest, *fwd[-1], max_dist=limit)
        source = "skeleton" if skin_elbow is None else "forearm+skeleton"
    elif elbow is None:
        elbow = _snap(mask, nearest, shoulder[0] + height * 0.16,
                      shoulder[1] + sign * height * 0.02, max_dist=limit)
    hand = _hand_near(skin_mask, wrist, height) if wrist is not None else None
    if hand is None:
        # Occluded forearm (e.g. hands behind the back): complete the bone by
        # pose, never by the cloth silhouette, and flag it as estimated.
        min_wrist_y = visible_to[1] + 0.03 * height if visible_to else None
        wrist = _hidden_wrist(side, guide, height, min_y=min_wrist_y)
        fore_estimated = True
    else:
        fore_estimated = False
    rad = max(3, int(round(height * 0.035)))
    upper_mid = (0.45 * shoulder[0] + 0.55 * elbow[0],
                 0.45 * shoulder[1] + 0.55 * elbow[1])
    upper_w = min(height * 0.06, _width(edt, upper_mid[0], upper_mid[1], rad))
    fore_w = min(height * 0.05, _width(edt, elbow[0], elbow[1], rad))
    return {
        "id": f"arm_{side}", "side": side, "visible": True,
        "partial": fore_estimated, "fore_estimated": fore_estimated,
        "shoulder": [shoulder[1], shoulder[0]],
        "elbow": [elbow[1], elbow[0]],
        "wrist": [wrist[1], wrist[0]],
        "visible_from": visible_from, "visible_to": visible_to,
        "hand": hand,
        "widths": {"upper": upper_w, "fore": fore_w},
        "joint_r": {"shoulder": max(3.0, upper_w / 2),
                    "elbow": max(3.0, fore_w / 2),
                    "wrist": max(2.0, fore_w / 2)},
        "source": source,
    }


def _visible_leg_mass(side, guide, skin_mask):
    """Largest skin component below the waist on one side (may be tiny)."""
    height, width = skin_mask.shape
    center = guide["center_x"]
    lab, n = label(skin_mask, structure=np.ones((3, 3), bool))
    best = None
    for i in range(1, n + 1):
        ys, xs = np.where(lab == i)
        if len(ys) < max(24, int(height * width * 0.0004)):
            continue
        if ys.min() < guide["waist_y"] + 0.02 * height:
            continue
        if ys.max() < height * 0.80:
            continue
        cx = float(np.median(xs))
        if (cx < center) != (side == "left"):
            continue
        if abs(cx - center) > width * 0.30:
            continue
        if best is None or len(ys) > best[0]:
            best = (len(ys), ys, xs)
    return None if best is None else (best[1], best[2])


def _leg(side, guide, skin_mask, height):
    """Complete hip-knee-ankle chain; the thigh axis is anchored on visible skin.

    Joint heights come from the character proportions and lean with the sway
    axis.  Where the skirt hides the leg the segment is marked estimated and
    drawn dashed; the visible skin mass fixes the thigh direction so the
    estimated part still lines up with the real leg.
    """
    sign = -1.0 if side == "left" else 1.0
    tw = guide["torso_width"]
    waist = guide.get("anatomy_waist_y", guide["waist_y"])
    torso_len = max(1.0, waist - guide["shoulder_y"])
    py = guide.get("pelvis_y", waist + 0.30 * torso_len)
    band = guide.get("pelvis_band")
    if band:
        pelvis_cx = 0.5 * (band[0] + band[1])
        pelvis_rx = max(4.0, 0.5 * (band[1] - band[0]))
    else:
        pelvis_cx = _axis_x(guide, py)
        pelvis_rx = 0.60 * tw
    pelvis_ry = 0.24 * torso_len
    # The hip line is level while standing; sockets sit a little below the
    # pelvis centre so both thighs start at the same height.
    slope = 0.0
    norm = math.hypot(1.0, slope)
    # Hip sockets sit in the lower-left/right pelvis, in the ellipse's own
    # rotated frame, rather than on a horizontal line through its centre.
    ux, uy = 1.0 / norm, -slope / norm
    vx, vy = slope / norm, 1.0 / norm
    hip = np.array([
        pelvis_cx + sign * 0.45 * pelvis_rx * ux + 0.36 * pelvis_ry * vx,
        py + sign * 0.45 * pelvis_rx * uy + 0.36 * pelvis_ry * vy,
    ])

    mass = _visible_leg_mass(side, guide, skin_mask)
    visible_from = visible_to = None
    thigh_w = 0.18 * tw
    if mass is not None:
        ys, xs = mass
        top, bot = int(ys.min()), int(ys.max())
        span = max(1, bot - top)
        top_band = ys <= top + max(1, span * 0.15)
        bot_band = ys >= bot - max(1, span * 0.15)
        visible_from = [float(np.median(xs[top_band])), float(top)]
        visible_to = [float(np.median(xs[bot_band])), float(bot)]
        band = (ys >= top) & (ys <= top + max(1, span * 0.30))
        thigh_w = min(height * 0.14, max(6.0, float(
            np.percentile(xs[band], 95) - np.percentile(xs[band], 5))))

    if visible_to is not None:
        # Center each socket over its measured thigh, biased towards the body.
        # This preserves the asymmetric stance instead of mirroring bad hips.
        socket_x = visible_to[0] - sign * 0.08 * tw
        hip[0] = float(np.clip(socket_x, pelvis_cx - pelvis_rx,
                               pelvis_cx + pelvis_rx))
        # A-line stance: the thigh runs from the hip towards the visible leg.
        direction = np.array(visible_to) - hip
    else:
        direction = np.array([0.0, 1.0])
    norm = float(np.hypot(*direction))
    direction = direction / norm if norm > 1e-6 else np.array([0.0, 1.0])

    # Joint heights come from the character's head-to-body ratio, so a cropped
    # figure still gets anatomically placed knees/ankles instead of guesses
    # tied to the crop size.
    full_h = guide.get("full_h")
    head_top = guide.get("head_top", 0.0)
    knee_y = head_top + 0.74 * full_h if full_h else hip_y + torso_len
    ankle_y = head_top + 0.96 * full_h if full_h else hip_y + 2.0 * torso_len

    def at(y):
        t = (y - hip[1]) / max(direction[1], 1e-6)
        return hip + direction * t

    knee = at(knee_y)
    ankle = at(ankle_y)

    cropped = bool(knee[1] > height - 2)
    out = {
        "id": f"leg_{side}", "side": side, "visible": True,
        "partial": True, "cropped": cropped,
        "hip": hip.tolist(),
        "knee": None if cropped else knee.tolist(),
        "ankle": None if ankle[1] > height - 2 else ankle.tolist(),
        "foot": None,
        "visible_from": visible_from, "visible_to": visible_to,
        "widths": {"thigh": float(thigh_w), "shin": float(thigh_w * 0.62)},
        "joint_r": {"hip": max(3.0, thigh_w / 2),
                    "knee": None if cropped else max(3.0, thigh_w * 0.35),
                    "ankle": None},
        "source": "proportional",
    }
    if out["ankle"] is not None:
        out["foot"] = {"cx": out["ankle"][0], "cy": out["ankle"][1],
                       "w": thigh_w * 0.62 * 1.5, "h": thigh_w * 0.62 * 0.7}
        out["joint_r"]["ankle"] = max(2.0, thigh_w * 0.31)
        out["partial"] = False
    return out


def derive_limbs(body_mask: np.ndarray, skin_mask: np.ndarray, guide: dict):
    """Return ``{"arms": [...], "legs": [...]}`` in detection coordinates."""
    height, width = body_mask.shape
    mask = binary_fill_holes(binary_closing(body_mask, iterations=1))
    edt_raw, nearest = distance_transform_edt(~mask, return_indices=True)
    edt = distance_transform_edt(mask)
    skel = zhang_suen(mask)
    segs = _segments(skel, edt)

    shoulder = guide.get("shoulder_y", height * 0.35)
    waist = guide.get("anatomy_waist_y", guide.get("waist_y", height * 0.72))
    center = guide.get("center_x", width / 2)
    torso_w = guide.get("torso_width", width * 0.45)

    arms_pick = _pick_side(segs, center, shoulder - height * 0.12,
                           waist + height * 0.22, height * 0.08, torso_w * 0.55)
    arms = [_arm(side, guide, edt, nearest, mask, skin_mask, height,
                 arms_pick[side]) for side in ("left", "right")]
    legs = [_leg(side, guide, skin_mask, height) for side in ("left", "right")]
    return {"arms": arms, "legs": legs}


def scale_structure(structure: dict, k: float) -> dict:
    """Scale every coordinate-ish field by ``k`` (detection → working canvas)."""
    out = copy.deepcopy(structure)
    out["unit"] = float(out.get("unit", 1.0)) * k

    def pt(p):
        return [float(p[0]) * k, float(p[1]) * k]

    if "head" in out:
        for key in ("x", "top", "cx", "cy", "rx", "ry"):
            if key in out["head"]:
                out["head"][key] *= k
        if out["head"].get("chin"):
            out["head"]["chin"] = pt(out["head"]["chin"])
        if out["head"].get("axis"):
            out["head"]["axis"] = [pt(p) for p in out["head"]["axis"]]
    for name in ("waist", "pelvis"):
        if name in out:
            for key in ("cx", "cy", "rx", "ry"):
                out[name][key] *= k
    for key in ("neck", "shoulder_y", "waist_y"):
        if key in out:
            out[key] = pt(out[key]) if key == "neck" else out[key] * k
    for key in ("shoulder_line", "waist_line"):
        if key in out:
            out[key] = [pt(p) for p in out[key]]
    if "torso" in out:
        for key in ("center_x", "left", "right", "width"):
            out["torso"][key] *= k
    if "bust" in out:
        for lobe in out["bust"].get("lobes", []):
            for key in ("cx", "cy", "rx", "ry"):
                lobe[key] *= k
    for side, pts in (out.get("seams") or {}).items():
        out["seams"][side] = [pt(p) for p in pts]

    limbs = out.get("limbs") or {}
    for arm in limbs.get("arms", []):
        for key in ("shoulder", "elbow", "wrist", "visible_from", "visible_to"):
            if arm.get(key):
                arm[key] = pt(arm[key])
        if arm.get("hand"):
            arm["hand"] = {kk: (vv * k) for kk, vv in arm["hand"].items()}
        for group in ("widths", "joint_r"):
            for kk, vv in (arm.get(group) or {}).items():
                if vv is not None:
                    arm[group][kk] = vv * k
    for leg in limbs.get("legs", []):
        for key in ("hip", "knee", "ankle", "visible_from", "visible_to"):
            if leg.get(key):
                leg[key] = pt(leg[key])
        if leg.get("foot"):
            leg["foot"] = {kk: (vv * k) for kk, vv in leg["foot"].items()}
        for group in ("widths", "joint_r"):
            for kk, vv in (leg.get(group) or {}).items():
                if vv is not None:
                    leg[group][kk] = vv * k
    return out


def _line(draw, pts, color, width):
    pts = [(float(x), float(y)) for x, y in pts]
    draw.line(pts, fill=color, width=width, joint="curve")


def _dashed(draw, p0, p1, color, width, dash):
    """Dashed segment for pose-estimated (occluded / out-of-crop) bones."""
    length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    if length < 1e-6:
        return
    n = max(1, int(length / max(1.0, dash)))
    for i in range(0, n, 2):
        t0, t1 = i / n, min(1.0, (i + 1) / n)
        a = (p0[0] + (p1[0] - p0[0]) * t0, p0[1] + (p1[1] - p0[1]) * t0)
        b = (p0[0] + (p1[0] - p0[0]) * t1, p0[1] + (p1[1] - p0[1]) * t1)
        draw.line([a, b], fill=color, width=width)


def _circle(draw, cx, cy, r, color, width):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=width)


def _ellipse(draw, shape, color, width):
    """Ellipse whose vertical axis follows the measured anatomical tilt."""
    tilt = float(shape.get("tilt", 0.0))
    norm = math.hypot(1.0, tilt)
    ux, uy = 1.0 / norm, -tilt / norm
    vx, vy = tilt / norm, 1.0 / norm
    points = []
    for i in range(96):
        a = 2.0 * math.pi * i / 96
        ca, sa = math.cos(a), math.sin(a)
        points.append((shape["cx"] + shape["rx"] * ca * ux + shape["ry"] * sa * vx,
                       shape["cy"] + shape["rx"] * ca * uy + shape["ry"] * sa * vy))
    draw.line(points + [points[0]], fill=color, width=width, joint="curve")


def render_structure(structure: dict, width: int, height: int, unit: float) -> Image.Image:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    lw = max(2, int(round(2 * unit)))
    jw = max(1, int(round(0.8 * unit)))
    dash = max(4.0, 3.0 * unit)

    for key in ("shoulder_line", "waist_line"):
        line = structure.get(key)
        if line:
            _line(d, line, COLORS["frame"], lw)
    if structure.get("neck") and structure.get("waist_line"):
        wl = structure["waist_line"]
        mid = [(wl[0][0] + wl[1][0]) / 2, (wl[0][1] + wl[1][1]) / 2]
        _line(d, [structure["neck"], mid], COLORS["frame"], max(1, lw // 2))
    head = structure.get("head") or {}
    neck = structure.get("neck")
    if head.get("rx"):
        _ellipse(d, head, COLORS["frame"], lw)
    for name in ("waist", "pelvis"):
        shape = structure.get(name) or {}
        if shape.get("rx"):
            _ellipse(d, shape, COLORS["frame"], lw)
    if head and neck:
        axis = head.get("axis") or [(head["x"], head["top"])]
        if not head.get("axis") and head.get("chin"):
            axis.append(head["chin"])
        axis = list(axis) + [neck]
        _line(d, axis, COLORS["frame"], lw)
        _circle(d, axis[0][0], axis[0][1], max(2.0, 0.35 * unit), COLORS["frame"], lw)
    # Seam polylines remain available as measurements, but are not structure
    # overlay primitives: beside the bust they read as spurious body outlines.
    bust = structure.get("bust") or {}
    for lobe in bust.get("lobes", []):
        d.ellipse([lobe["cx"] - lobe["rx"], lobe["cy"] - lobe["ry"],
                   lobe["cx"] + lobe["rx"], lobe["cy"] + lobe["ry"]],
                  outline=COLORS["bust"], width=lw)

    for arm in (structure.get("limbs") or {}).get("arms", []):
        pts = [arm["shoulder"], arm["elbow"]]
        _line(d, pts, COLORS["arm"], lw)
        if arm.get("wrist"):
            # One straight forearm axis; partial/occluded axes stay dashed.
            if arm.get("fore_estimated"):
                _dashed(d, arm["elbow"], arm["wrist"], COLORS["arm"], lw, dash)
            else:
                _line(d, [arm["elbow"], arm["wrist"]], COLORS["arm"], lw)
        for name in ("shoulder", "elbow", "wrist"):
            p = arm.get(name)
            if p and arm["joint_r"].get(name):
                _circle(d, p[0], p[1], arm["joint_r"][name], COLORS["arm"], jw)
        if arm.get("hand"):
            h = arm["hand"]
            d.ellipse([h["cx"] - h["r"], h["cy"] - h["r"],
                       h["cx"] + h["r"], h["cy"] + h["r"]], fill=COLORS["hand"])

    for leg in (structure.get("limbs") or {}).get("legs", []):
        # A thigh is one straight axis, never a polyline through skin samples.
        thigh_end = leg.get("knee") or leg.get("visible_to") or leg.get("visible_from")
        if thigh_end:
            if leg.get("partial"):
                _dashed(d, leg["hip"], thigh_end, COLORS["leg"], lw, dash)
            else:
                _line(d, [leg["hip"], thigh_end], COLORS["leg"], lw)
        if leg.get("knee") and leg.get("ankle"):
            _line(d, [leg["knee"], leg["ankle"]], COLORS["leg"], lw)
        for name in ("hip", "knee", "ankle"):
            p = leg.get(name)
            if p and leg["joint_r"].get(name):
                _circle(d, p[0], p[1], leg["joint_r"][name], COLORS["leg"], jw)
        if leg.get("foot"):
            f = leg["foot"]
            d.ellipse([f["cx"] - f["w"] / 2, f["cy"] - f["h"] / 2,
                       f["cx"] + f["w"] / 2, f["cy"] + f["h"] / 2],
                      fill=COLORS["hand"])
    return img


def write_check_image(source_crop: Image.Image, structure: dict,
                      out_path, max_h: int = 900) -> None:
    """White-washed source + structure overlay, for human confirmation."""
    sw, sh = source_crop.size
    overlay = render_structure(structure, sw, sh, structure.get("unit", 1.0))
    scale = min(1.0, max_h / float(sh))
    size = (max(1, int(round(sw * scale))), max(1, int(round(sh * scale))))
    base = source_crop.resize(size, Image.LANCZOS).convert("RGB")
    wash = Image.blend(base, Image.new("RGB", size, (255, 255, 255)), 0.62)
    over = overlay.resize(size, Image.LANCZOS)
    Image.alpha_composite(wash.convert("RGBA"), over).convert("RGB").save(out_path)
