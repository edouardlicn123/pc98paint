# -*- coding: utf-8 -*-
"""人物线稿与布料绘制语义；只处理掩码、几何和配置，不写文件。"""
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import (binary_closing, binary_dilation,
                           distance_transform_edt, gaussian_filter, label)

from bust_sample2 import zhang_suen

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


def rim_shadow(mask, fg, ratio=0.02):
    """右侧轮廓内侧的暗带；裁切边与组内材质接缝不算轮廓。"""
    ys, xs = np.where(mask)
    if not len(ys):
        return np.zeros(mask.shape, dtype=bool)
    k = max(2, int(round(mask.shape[1] * ratio)))
    sil = binary_closing(mask, structure=CONNECT8)
    p = k + 2
    dist = distance_transform_edt(np.pad(sil, p, mode="edge"))[p:-p, p:-p]
    yy, xx = np.mgrid[0:mask.shape[0], 0:mask.shape[1]]
    shadow = mask & (dist <= k) & (xx >= xs.mean())
    fy, _ = np.where(fg)
    cut = yy >= fy.max() - (k + 1)
    right = np.full(mask.shape[0], -10 ** 6)
    for y in range(mask.shape[0]):
        row = np.where(mask[y])[0]
        if row.size:
            right[y] = row.max()
    shadow &= (~cut) | (xx >= right[:, None] - k)
    lab, n = label(shadow)
    for i in range(1, n + 1):
        comp = lab == i
        if not (comp & ~cut).any():
            shadow &= ~comp
    return shadow


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


def build_cloth_layers(rgb, fg, material_idx, materials, config=None):
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

    # 体积暗面沿用既有组级轮廓规则，不沿同组接缝生成暗带。
    groups = {}
    for i, material in enumerate(materials):
        if material.get("role") == "cloth":
            groups.setdefault(material.get("group") or material["id"], []).append(i)
    for members in groups.values():
        union = np.isin(material_idx, members)
        if not union.any():
            continue
        shadow = rim_shadow(union, fg)
        form |= shadow
        for i in members:
            tones["form"][material_idx == i] = len(materials[i].get("refs", [])) - 1

    # 白衣既有的大块第二色归入 form，保证迁移前后不丢影。
    for i, material in enumerate(materials):
        refs = material.get("refs", [])
        if material.get("role") != "white" or len(refs) < 2:
            continue
        mask = material_idx == i
        lab, n = label(mask)
        big = np.zeros(shape, dtype=bool)
        for j in range(1, n + 1):
            comp = lab == j
            if comp.sum() >= 200:
                big |= comp
        ref0, ref1 = _hex_rgb(refs[0]), _hex_rgb(refs[1])
        d0 = ((rgb.astype(np.float32) - ref0) ** 2).sum(-1)
        d1 = ((rgb.astype(np.float32) - ref1) ** 2).sum(-1)
        white_form = big & (d1 < d0)
        form |= white_form
        tones["form"][white_form] = 1

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
        if cfg.get("path"):
            points = _points(cfg["path"], _bbox(under))
            candidate = _stroke(shape, points, float(cfg.get("width", 2)), "seam")
        else:
            candidate = binary_dilation(
                over, iterations=max(1, int(round(cfg.get("width", 2)))))
        area = _clean_area(candidate & under)
        tone = _tone(materials[under_i], cfg,
                     len(materials[under_i].get("refs", [])) - 1)
        occlusion |= area
        tones["occlusion"][area] = tone
        stats["occlusions"].append({
            "over": cfg["over"], "under": cfg["under"],
            "pixels": int(area.sum()), "tone": tone,
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
