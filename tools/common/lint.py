# -*- coding: utf-8 -*-
"""立绘规格检查：不合格就拒绝进入下一步。"""
import numpy as np
from scipy.ndimage import binary_dilation, distance_transform_edt, label


def lint(img, spec):
    a = np.array(img)
    h, w = a.shape[:2]
    rgb = a[..., :3].astype(np.int16)
    fg = a[..., 3] > 0
    n = max(int(fg.sum()), 1)
    maxc, minc = rgb.max(axis=2), rgb.min(axis=2)
    chroma = maxc - minc
    lum = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    yy = np.mgrid[0:h, 0:w][0]

    # 纯黑是线稿、纯白是白衣/高光，都不属于"中性灰"
    neutral = float(((chroma < 12) & (lum > 20) & (lum < 235) & fg).sum() / n)
    # 线稿用纯黑，暗部彩度只统计非纯黑的暗像素
    dark = (lum > 20) & (lum < 100) & fg
    dark_chroma = float((chroma[dark] >= spec["checks"]["dark_chroma_min"]).mean()) if dark.any() else 0.0

    edge = fg & binary_dilation(~fg, iterations=1)
    outline = float((lum[edge] < 90).mean()) if edge.any() else 0.0

    hair = (lum < 100) & fg & (yy < int(h * 0.45))
    hair_tones = 0
    if hair.any():
        _, counts = np.unique(rgb[hair].reshape(-1, 3), axis=0, return_counts=True)
        hair_tones = int((counts / counts.sum() >= 0.005).sum())

    d_in = distance_transform_edt(fg)
    # 白衣与眼内高光必须是纯白；不允许被染成奶油色/灰绿。
    # 只统计“接近中性”的亮像素：暖肤色（chroma≈51）本身不是白衣，
    # 把它算进来会让该指标随露肤面积漂移，而不是反映白衣被染色。
    pale = (minc > 200) & (chroma <= 40) & fg & (d_in >= 2)
    white_purity = float((chroma[pale] <= 10).mean()) if pale.any() else 1.0

    r = spec["render"]
    c = spec["checks"]
    lo, hi = c["hair_tones"]
    checks = {
        "size": {"value": [w, h], "pass": h <= r["sprite_h"] and w <= r["sprite_w_max"]},
        "neutral_gray": {"value": neutral, "limit": c["neutral_gray_max"], "pass": neutral <= c["neutral_gray_max"]},
        "outline": {"value": outline, "limit": c["outline_min"], "pass": outline >= c["outline_min"]},
        "dark_chroma": {"value": dark_chroma, "limit": 0.90, "pass": dark_chroma >= 0.90},
        "hair_tones": {"value": hair_tones, "limit": [lo, hi], "pass": lo <= hair_tones <= hi},
        "white_purity": {"value": white_purity, "limit": 0.80, "pass": white_purity >= 0.80},
    }
    return {"pass": all(v["pass"] for v in checks.values()), "checks": checks}


def lint_materials(idx, materials, fg, baseline=None):
    """材质语义验收：检查皮肤/白衣冲突与同源图的材质面积突变。"""
    skin_i = [i for i, m in enumerate(materials) if m.get("role") == "skin"]
    white_i = [i for i, m in enumerate(materials) if m.get("role") == "white"]
    eye_i = [i for i, m in enumerate(materials) if m.get("role") == "eye"]
    cloth_i = [i for i, m in enumerate(materials) if m.get("role") == "cloth"]
    stats = {m["id"]: int((idx == i).sum()) for i, m in enumerate(materials)}
    checks = {}

    bad = 0
    if skin_i and white_i:
        skin = np.isin(idx, skin_i)
        eye = np.isin(idx, eye_i)
        eye_near = (binary_dilation(eye, iterations=4)
                    if eye_i else np.zeros(fg.shape, bool))
        # 只有边缘确实连接虹膜/眼线的白块才算眼部结构；仅仅“靠近眼睛”不免检。
        min_hole = max(4, int(round(fg.sum() * 0.0002)))
        lab, n = label(np.isin(idx, white_i) & fg)
        for k in range(1, n + 1):
            comp = lab == k
            if comp.sum() < min_hole:
                continue
            eye_ring = binary_dilation(comp, iterations=1) & ~comp
            eye_ratio = ((eye_ring & (eye | (fg & (idx < 0)))).sum()
                         / max(int(eye_ring.sum()), 1))
            if (comp & eye_near).any() and eye_ratio >= 0.20:
                continue
            # Neckline/blouse panels enclosed by skin but bounded by collar or
            # other cloth are garment pieces, not skin holes.
            if cloth_i and (binary_dilation(comp, iterations=16)
                            & np.isin(idx, cloth_i)).any():
                continue
            ring = binary_dilation(comp, iterations=2) & ~comp
            if ring.sum() and (ring & skin).sum() / ring.sum() >= 0.35:
                bad += int(comp.sum())
    checks["skin_white_holes"] = {
        "value": bad, "limit": 0, "pass": bad == 0,
    }

    if baseline:
        expected = baseline.get("expected", {})
        tolerance = float(baseline.get("tolerance", 0.35))
        deviations = {
            mid: round(abs(stats.get(mid, 0) - px) / max(px, 1), 4)
            for mid, px in expected.items()
        }
        worst = max(deviations.values(), default=0.0)
        checks["material_area"] = {
            "value": worst, "limit": tolerance,
            "deviations": deviations, "pass": worst <= tolerance,
        }

    return {
        "pass": all(v["pass"] for v in checks.values()),
        "checks": checks,
        "stats": stats,
    }


def lint_drawing(fills, idx, materials, layers, drawing_report,
                 config=None, line_mask=None):
    """检查配置褶皱命中、布料层归属与布料黑色的合法来源。"""
    config = config or {}
    stats = drawing_report.get("folds", [])
    missing = []
    for i, cfg in enumerate(config.get("folds", [])):
        item = stats[i] if i < len(stats) else {}
        if not item.get("anchor_hit") or item.get("pixels", 0) <= 0:
            missing.append({"index": i, "material": cfg.get("material")})

    cloth_ids = [i for i, m in enumerate(materials)
                 if m.get("role") in ("white", "cloth")]
    cloth = np.isin(idx, cloth_ids)
    outside = 0
    for mask in layers.values():
        outside += int((mask & ~cloth).sum())

    black = np.all(fills[..., :3] == 0, axis=-1)
    allowed_black = layers.get("occlusion", np.zeros(idx.shape, bool)) | (idx < 0)
    if line_mask is not None:
        allowed_black = allowed_black | line_mask
    illegal_black = int((black & cloth & ~allowed_black).sum())
    checks = {
        "drawing_fold_anchors": {
            "value": len(missing), "limit": 0, "missing": missing,
            "pass": not missing,
        },
        "drawing_layer_bounds": {
            "value": outside, "limit": 0, "pass": outside == 0,
        },
        "drawing_cloth_black": {
            "value": illegal_black, "limit": 0, "pass": illegal_black == 0,
        },
    }
    return {"pass": all(v["pass"] for v in checks.values()), "checks": checks}
