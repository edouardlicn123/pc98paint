# -*- coding: utf-8 -*-
"""按 Lint 结果做最小修正：头发限色、去中性灰。"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
LIB = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))
import pc98_sprite_v7 as v7  # noqa: E402


def _kmeans(px, k=6, iters=8):
    lum = 0.299 * px[:, 0] + 0.587 * px[:, 1] + 0.114 * px[:, 2]
    order = np.argsort(lum)
    seeds = px[order[np.linspace(0, len(px) - 1, k).astype(int)]].astype(np.float64)
    for _ in range(iters):
        d = ((px[:, None, :] - seeds[None, :, :]) ** 2).sum(2)
        lab = d.argmin(1)
        for i in range(k):
            sel = lab == i
            if sel.any():
                seeds[i] = px[sel].mean(0)
    return seeds.clip(0, 255).astype(np.uint8)[lab]


def repair(img, spec, hair_k=6):
    a = np.array(img)
    rgb = a[..., :3].astype(np.int16)
    fg = a[..., 3] > 0
    h = a.shape[0]
    yy = np.mgrid[0:h, 0:a.shape[1]][0]
    lum = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    chroma = np.ptp(rgb, axis=2)

    # 1) 头发限色（保留最亮一档作为高光）
    hair = fg & (yy < int(h * 0.45)) & (lum < 105)
    if hair.sum() > 50:
        px = rgb[hair].astype(np.uint8)
        rgb[hair] = _kmeans(px, k=hair_k)

    # 2) 去除中性灰：低彩度中间调偏移到冷/暖色相，不再保留灰。
    #    lum>=235 的近白是白衣与高光，保持纯白，不再染成奶油色。
    gray = fg & (chroma < 12) & (lum < 235)
    if gray.any():
        lab = v7.rgb_to_lab(rgb[gray])
        L, aa, bb = lab[:, 0], lab[:, 1], lab[:, 2]
        hue = np.radians(np.where(L < 50, 285.0, 45.0))
        C = np.maximum(np.hypot(aa, bb), 14.0)
        lab = np.stack([L, C * np.cos(hue), C * np.sin(hue)], -1)
        rgb[gray] = np.clip(v7.lab_to_rgb(lab), 0, 255).astype(np.int16)

    out = np.dstack([rgb.astype(np.uint8), a[..., 3]])
    return Image.fromarray(out, "RGBA")


def palette_lock(img, spec, passes=2):
    """把前景色锁定到材质色板：消除近似重复色、灰色与孤立杂点。

    - 以 Lab 最近色归并：量化产生的成百上千个近似色收敛为每种材质 2-4 阶；
    - 色板中不含中性灰，暗部一律给带色相的蓝紫/藕荷，避免“用灰压暗”；
    - 3×3 邻域去杂点：同色邻居 <=1 的像素改用邻居多数色，清掉碎裂噪点。
    """
    cfg = spec.get("clean_palette")
    if not cfg:
        return img
    pal = np.array(cfg, dtype=np.int16).reshape(-1, 3)
    a = np.array(img)
    h, w = a.shape[:2]
    fg = a[..., 3] > 0
    if not fg.any():
        return img
    rgb = a[..., :3].astype(np.int16)
    pal_lab = np.asarray(v7.rgb_to_lab(pal.astype(np.float64)), dtype=np.float64)
    src_lab = np.asarray(v7.rgb_to_lab(rgb[fg].astype(np.float64)), dtype=np.float64)
    dist = ((src_lab[:, None, :] - pal_lab[None, :, :]) ** 2).sum(2)
    idx = np.full((h, w), -1, dtype=np.int16)
    idx[fg] = dist.argmin(1)

    for _ in range(max(int(passes), 0)):
        pad = np.pad(idx, 1, mode="edge")
        neigh = np.stack([
            pad[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
            for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy, dx) != (0, 0)
        ])
        same = (neigh == idx[None]).sum(0)
        counts = np.stack([(neigh == k).sum(0) for k in range(len(pal))])
        major = counts.argmax(0).astype(np.int16)
        idx = np.where(fg & (same <= 1), major, idx)

    rgb[fg] = pal[np.clip(idx[fg], 0, len(pal) - 1)]
    out = np.dstack([rgb.astype(np.uint8), a[..., 3]])
    return Image.fromarray(out, "RGBA")


def drop_specks(img, max_area=6):
    """清掉与主体脱离的 1-3px 碎点（抗锯齿残渣），保留发丝块等有效结构。"""
    from scipy.ndimage import label

    a = np.array(img)
    fg = a[..., 3] > 0
    lab, n = label(fg)
    if n <= 1:
        return img
    sizes = np.bincount(lab.ravel())
    keep = sizes >= max_area
    keep[0] = False
    body = lab == int(np.argmax(sizes[1:]) + 1)
    remove = fg & (~keep[lab]) & (~body)
    if remove.any():
        a[..., 3][remove] = 0
        return Image.fromarray(a, "RGBA")
    return img


def eyebrow_fix(img, spec):
    """按角色锚点整理眉线；小结构回退实色，不清空双眼皮线。"""
    cfg = spec.get("eyebrow_fix")
    if not cfg:
        return img
    a = np.array(img)
    h, w = a.shape[:2]
    rw, rh = cfg["reference_size"]
    sx, sy = w / rw, h / rh
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    for line in cfg["lines"]:
        points = [(round(x * sx), round(y * sy)) for x, y in line]
        draw.line(points, fill=255, width=1)
    brows = np.array(mask) > 0

    boxes = np.zeros(brows.shape, dtype=bool)
    for x0, y0, x1, y1 in cfg["cleanup_boxes"]:
        xa, xb = sorted((round(x0 * sx), round(x1 * sx)))
        ya, yb = sorted((round(y0 * sy), round(y1 * sy)))
        boxes[max(ya, 0):min(yb, h), max(xa, 0):min(xb, w)] = True

    rgb = a[..., :3].astype(np.int16)
    fg = a[..., 3] > 0
    lum = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    # 近黑像素用于保留与眉区相接的刘海；其余非眉线过渡色归回肤色。
    cleanup = boxes & (~brows) & (lum >= 45) & fg
    rgb[cleanup] = np.array(cfg["skin_color"], dtype=np.int16)
    rgb[brows & fg] = np.array(cfg["line_color"], dtype=np.int16)
    out = np.dstack([rgb.astype(np.uint8), a[..., 3]])
    return Image.fromarray(out, "RGBA")
