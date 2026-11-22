# -*- coding: utf-8 -*-
"""A/B/C 三种立绘生成路线对比。

A 结构重绘：高分辨率分色 → 区域众数下采样 → 轮廓重画 1px → 交界异色交错。
B 条件生成：按设定重新生成 1536×3200 → 线稿保持型像素化。
C 原生采样：最近邻直接落到目标分辨率 → 量化 + 轮廓线。
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation, binary_fill_holes, distance_transform_edt, label, minimum_filter, uniform_filter
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import pc98_sprite_v7 as v7  # noqa: E402


def fit_size(im, max_h=640, max_w=300):
    h = max_h
    w = round(im.width * h / im.height)
    if w > max_w:
        w = max_w
        h = round(im.height * w / im.width)
    return im, w, h


def alpha_from_bg(hi, w, h, rgb_out):
    fa = np.array(hi)
    wmin = fa.min(axis=2)
    near = wmin > 245
    lab, _ = label(near)
    border = np.unique(np.r_[lab[0], lab[-1], lab[:, 0], lab[:, -1]])
    bg_hi = np.isin(lab, border[border > 0])
    dist = distance_transform_edt(~bg_hi)
    zone = (~bg_hi) & (dist <= 3)
    a = np.ones(wmin.shape, np.float32)
    a[bg_hi] = 0
    a[zone] = np.clip((250.0 - wmin[zone]) / 70.0, 0, 1)
    small = np.array(Image.fromarray((a * 255).astype(np.uint8)).resize((w, h), Image.BOX)) / 255.0
    fg = small > 0.5
    return fg


def save(rgba, name):
    img = Image.fromarray(rgba, "RGBA")
    img.save(ROOT / "pc98" / f"pc98_abc_{name}.png")
    prev = Image.new("RGB", (640, 640), (92, 96, 104))
    prev.paste(img, ((640 - img.width) // 2, 640 - img.height), img)
    prev.save(ROOT / "pc98" / f"pc98_abc_{name}_preview.png")
    print(name, img.size, "colors", len(np.unique(rgba[..., :3][rgba[..., 3] > 0].reshape(-1, 3), axis=0)))


# ---------- A：结构重绘 ----------
def build_a(front):
    front, w, h = fit_size(front)
    from PIL import ImageFilter

    front = front.filter(ImageFilter.MedianFilter(5)).filter(ImageFilter.MedianFilter(5))
    n = 48
    q = front.quantize(colors=n, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
    labels = np.array(q)
    pal = np.array(q.getpalette()[: n * 3], dtype=np.uint8).reshape(-1, 3)
    lab_pal = v7.rgb_to_lab(pal)

    # 区域众数下采样：每个标签单独做面积平均，取最大
    votes = np.stack([
        np.array(Image.fromarray(((labels == i) * 255).astype(np.uint8)).resize((w, h), Image.BOX), dtype=np.float32)
        for i in range(n)
    ])
    lab_s = uniform_filter(votes, size=(1, 3, 3)).argmax(axis=0)
    out = pal[lab_s]

    # 1px 轮廓：只在色差明显的边界画，避免把噪点当轮廓
    edge = np.zeros((h, w), bool)
    for dy, dx in ((0, 1), (1, 0)):
        b = np.roll(lab_s, (dy, dx), axis=(0, 1))
        d = lab_s != b
        dist = np.linalg.norm(lab_pal[lab_s] - lab_pal[b], axis=2)
        d &= dist > 22
        edge |= d
        darker = np.where(pal[lab_s].sum(2) < pal[b].sum(2), lab_s, b)
        out[d] = pal[darker[d]]

    # 交界异色交错：暗侧 1px 带内，按 Bayer 混入相邻较亮区颜色
    bay = v7.BAYER
    yy, xx = np.mgrid[0:h, 0:w]
    band = binary_dilation(edge, iterations=1) & (~edge)
    for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0)):
        nb = np.roll(lab_s, (dy, dx), axis=(0, 1))
        brighter = pal[nb].sum(2) > pal[lab_s].sum(2)
        mix = band & brighter & (lab_s != nb) & (bay[yy % 8, xx % 8] < 0.5)
        out[mix] = pal[nb[mix]]

    fg = alpha_from_bg(front, w, h, out)
    bg_idx = np.array([c.min() > 235 for c in pal])
    fg &= ~bg_idx[lab_s]
    rgba = np.dstack([out, np.where(fg, 255, 0)]).astype(np.uint8)
    save(rgba, "A")


# ---------- B：条件生成 ----------
def build_b(path):
    im = Image.open(path).convert("RGB")
    a = np.array(im)
    mask = (a < 245).any(axis=2)
    rows = np.flatnonzero(mask.sum(1) > 3)
    cols = np.flatnonzero(mask.sum(0) > 3)
    im = im.crop((cols[0], rows[0], cols[-1] + 1, rows[-1] + 1))
    im, w, h = fit_size(im)
    mid = im.resize((w * 2, h * 2), Image.BOX)
    color = mid.resize((w, h), Image.BOX)
    lmask, lcolor = v7.line_layer(mid, (w, h))

    q = color.quantize(colors=96, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
    base = np.array(q.getpalette()[: 96 * 3], dtype=np.uint8).reshape(-1, 3)
    part = v7.partner_of(base)
    pal = np.vstack([base, part])
    rgb = np.array(color)
    _, idx = cKDTree(v7.rgb_to_lab(pal)).query(v7.rgb_to_lab(rgb).reshape(-1, 3), workers=-1)
    idx = idx.reshape(h, w)

    phi = v7.direction(color)
    yy, xx = np.mgrid[0:h, 0:w]
    th = v7.BAYER[np.floor(-xx * np.sin(phi) + yy * np.cos(phi)).astype(int) % 8,
                  np.floor(xx * np.cos(phi) + yy * np.sin(phi)).astype(int) % 8]
    lum = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    gy, gx = np.gradient(lum)
    flat = (np.abs(gy) + np.abs(gx) < 6) & (~lmask)
    use = flat & (th < 0.35) & (idx < len(base))
    out_idx = idx.copy()
    out_idx[use] = idx[use] + len(base)
    out = pal[out_idx]

    lq = Image.fromarray(lcolor).quantize(colors=16, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
    lpal = np.array(lq.getpalette()[:48], dtype=np.uint8).reshape(-1, 3)
    _, lidx = cKDTree(v7.rgb_to_lab(lpal)).query(v7.rgb_to_lab(lcolor).reshape(-1, 3), workers=-1)
    out[lmask] = lpal[lidx.reshape(h, w)][lmask]

    fg = alpha_from_bg(im, w, h, out)
    rgba = np.dstack([out, np.where(fg, 255, 0)]).astype(np.uint8)
    save(rgba, "B")


# ---------- C：最近邻原生采样 ----------
def build_c(front):
    front, w, h = fit_size(front)
    small = front.resize((w, h), Image.NEAREST)
    q = small.quantize(colors=128, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
    out = np.array(q.convert("RGB"))

    # 特征印章：块内最暗像素，把被最近邻采样漏掉的嘴线、睫毛补回来
    lhi = np.array(front.convert("L")).astype(np.float32)
    lmin = np.array(Image.fromarray(minimum_filter(lhi, size=5).astype(np.uint8)).resize((w, h), Image.BOX))
    lum = 0.299 * out[..., 0] + 0.587 * out[..., 1] + 0.114 * out[..., 2]
    feat = (lmin < 55) & (lum > 90)
    out[feat] = np.array([18, 16, 30], np.uint8)

    # 发丝补洞：浅色像素若 3×3 邻域多数是深色，就用邻域深色均值填回
    for _ in range(3):
        lum = 0.299 * out[..., 0] + 0.587 * out[..., 1] + 0.114 * out[..., 2]
        dark = (lum < 80).astype(np.float64)
        cnt = uniform_filter(dark, size=3) * 9
        pale = lum > 145
        fill = pale & (cnt >= 5)
        num = uniform_filter(out * dark[..., None], size=(3, 3, 1))
        den = uniform_filter(dark, size=3)[..., None]
        mean = np.where(den > 0.1, num / np.maximum(den, 1e-6), out)
        out[fill] = mean[fill].astype(np.uint8)

    fg = alpha_from_bg(front, w, h, out)
    fg = binary_fill_holes(fg)

    # 清掉被深色包围的浅色小碎块（发丝间的白点），大块额头保留
    lum = 0.299 * out[..., 0] + 0.587 * out[..., 1] + 0.114 * out[..., 2]
    pale_lab, npale = label(fg & (lum > 150))
    dark = (lum < 80) & fg
    sizes = np.bincount(pale_lab.ravel())
    for i in range(1, npale):
        if sizes[i] >= 45:
            continue
        ys, xs = np.where(pale_lab == i)
        y0, y1 = max(0, ys.min() - 2), min(h, ys.max() + 3)
        x0, x1 = max(0, xs.min() - 2), min(w, xs.max() + 3)
        ring = dark[y0:y1, x0:x1]
        if ring.mean() > 0.45:
            patch = out[y0:y1, x0:x1][ring]
            out[ys, xs] = patch.mean(axis=0).astype(np.uint8)

    rgba = np.dstack([out, np.where(fg, 255, 0)]).astype(np.uint8)
    save(rgba, "C")


sheet = Image.open(ROOT / "_work" / "pc98_src" / "girl_sheet_hi.jpg").convert("RGB")
front = v7.extract_front(sheet)
build_a(front)
build_b(ROOT / "_work" / "pc98_src" / "girl_full_hi.jpg")
build_c(front)
