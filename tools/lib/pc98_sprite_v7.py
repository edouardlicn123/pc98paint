# -*- coding: utf-8 -*-
"""v7：三视图 → 300×640 全身立绘。

- 从三视图切出正面视图；
- 以高度 640 为基准缩放（宽度上限 300）；
- 2× 提线、1× 合成 1px 线稿；
- 96 原色 + 伙伴色，平坦区 1px 交错；
- 输出 RGBA 与索引 0 透明的 P 模式 PNG。
"""
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation, label, uniform_filter
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]


def srgb_to_linear(c):
    c = c.astype(np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(x):
    x = np.clip(x, 0.0, 1.0)
    c = np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)
    return np.clip(c * 255.0, 0, 255)


M = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
WHITE = np.array([0.95047, 1.0, 1.08883])


def rgb_to_lab(rgb):
    c = srgb_to_linear(rgb)
    xyz = (c @ M.T) / WHITE
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)


def lab_to_rgb(lab):
    fy = (lab[..., 0] + 16) / 116
    f = np.stack([fy + lab[..., 1] / 500, fy, fy - lab[..., 2] / 200], axis=-1)
    xyz = np.where(f > 0.206897, f**3, (f - 16 / 116) / 7.787) * WHITE
    return linear_to_srgb(xyz @ np.linalg.inv(M).T)


def partner_of(rgb, deg=25.0):
    lab = rgb_to_lab(rgb)
    L = lab[..., 0]
    C = np.hypot(lab[..., 1], lab[..., 2])
    h = np.degrees(np.arctan2(lab[..., 2], lab[..., 1]))
    diff = (np.where(L < 50, 285.0, 55.0) - h + 180.0) % 360.0 - 180.0
    h2 = h + np.clip(diff, -deg, deg)
    r = np.radians(h2)
    return np.clip(lab_to_rgb(np.stack([L, C * 0.9 * np.cos(r), C * 0.9 * np.sin(r)], axis=-1)), 0, 255).astype(np.uint8)


def make_bayer(n):
    if n == 1:
        return np.zeros((1, 1))
    b = make_bayer(n // 2)
    return np.block([[4 * b, 4 * b + 2], [4 * b + 3, 4 * b + 1]]) / (n * n)


BAYER = make_bayer(8)


def extract_front(sheet):
    arr = np.array(sheet).copy()
    # 去掉脚底的水平基准线
    h = arr.shape[0]
    for y in range(int(h * 0.9), h):
        row = arr[y]
        nonwhite = (row < 245).any(axis=1)
        grayish = (np.ptp(row, axis=1) < 14) & (row.mean(axis=1) < 235)
        if nonwhite.mean() > 0.6 and grayish.mean() > 0.6:
            arr[y] = 255

    mask = (arr < 245).any(axis=2)
    cols = mask.sum(axis=0)
    on = cols > 3
    # 找连续列段
    idx = np.flatnonzero(np.diff(np.r_[False, on, False]))
    runs = [(idx[i], idx[i + 1]) for i in range(0, len(idx), 2)]
    runs = [r for r in runs if r[1] - r[0] > 80]
    runs.sort(key=lambda r: r[1] - r[0], reverse=True)
    runs = sorted(runs[:3])  # 左中右
    x0, x1 = runs[0]
    rows = np.flatnonzero(mask[:, x0:x1].sum(axis=1) > 1)
    y0, y1 = rows[0], rows[-1] + 1
    return Image.fromarray(arr[y0:y1, x0:x1])


def direction(img):
    a = np.array(img).astype(np.float64)
    lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    gy, gx = np.gradient(lum)
    jxx, jyy, jxy = uniform_filter(gx * gx, 5), uniform_filter(gy * gy, 5), uniform_filter(gx * gy, 5)
    phi = 0.5 * np.arctan2(2 * jxy, jxx - jyy) + np.pi / 2
    coh = np.sqrt((jxx - jyy) ** 2 + 4 * jxy**2) / (jxx + jyy + 1e-6)
    phi = np.where(coh < 0.2, 0.0, phi)
    sx, sy = uniform_filter(np.cos(2 * phi), 7), uniform_filter(np.sin(2 * phi), 7)
    return 0.5 * np.arctan2(sy, sx)


def line_layer(mid, target, contrast=30, dark=55, max_frac=0.6,
               strict_mask=None, return_features=False):
    a = np.array(mid).astype(np.float64)
    lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    contrast_edge = lum < uniform_filter(lum, 3) - contrast
    ink_core = lum < dark
    edge = contrast_edge | ink_core
    if strict_mask is not None:
        # 白衣浅灰阴影不能独立成线；对比边缘必须贴着真实深色线芯。
        near_core = binary_dilation(ink_core, iterations=2)
        edge = np.where(strict_mask, ink_core | (contrast_edge & near_core), edge)
    edge &= uniform_filter(edge.astype(np.float64), 7) < max_frac
    h, w = target[1], target[0]

    def downsample(values):
        return values.reshape(h, 2, w, 2).max(axis=(1, 3))

    mask = downsample(edge)
    blocks = a.reshape(h, 2, w, 2, 3).transpose(0, 2, 1, 3, 4).reshape(h, w, 4, 3)
    sl = 0.299 * blocks[..., 0] + 0.587 * blocks[..., 1] + 0.114 * blocks[..., 2]
    pick = sl.argmin(axis=-1)
    color = np.take_along_axis(blocks, pick[..., None, None], axis=2)[..., 0, :]
    if return_features:
        features = {
            "ink_core": downsample(ink_core & edge),
            "contrast_edge": downsample(contrast_edge & edge),
        }
        return mask, color.astype(np.uint8), features
    return mask, color.astype(np.uint8)


def main():
    sheet = Image.open(ROOT / "_work" / "pc98_src" / "girl_sheet_hi.jpg").convert("RGB")
    front = extract_front(sheet)
    h = 640
    w = round(front.width * h / front.height)
    if w > 300:
        w = 300
        h = round(front.height * w / front.width)
    mid = front.resize((w * 2, h * 2), Image.BOX)
    color = mid.resize((w, h), Image.BOX)
    lmask, lcolor = line_layer(mid, (w, h))

    q = color.quantize(colors=96, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
    base = np.array(q.getpalette()[: 96 * 3], dtype=np.uint8).reshape(-1, 3)
    part = partner_of(base)
    pal = np.vstack([base, part])
    rgb = np.array(color)
    _, idx = cKDTree(rgb_to_lab(pal)).query(rgb_to_lab(rgb).reshape(-1, 3), workers=-1)
    idx = idx.reshape(h, w)

    phi = direction(color)
    yy, xx = np.mgrid[0:h, 0:w]
    th = BAYER[np.floor(-xx * np.sin(phi) + yy * np.cos(phi)).astype(int) % 8,
               np.floor(xx * np.cos(phi) + yy * np.sin(phi)).astype(int) % 8]
    lum = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    gy, gx = np.gradient(lum)
    flat = (uniform_filter(np.hypot(gx, gy), 5) < 5.0) & (~lmask)
    use_partner = flat & (th < 0.35) & (idx < len(base))
    out_idx = idx.copy()
    out_idx[use_partner] = idx[use_partner] + len(base)
    out = pal[out_idx]

    lq = Image.fromarray(lcolor).quantize(colors=16, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
    lpal = np.array(lq.getpalette()[:48], dtype=np.uint8).reshape(-1, 3)
    _, lidx = cKDTree(rgb_to_lab(lpal)).query(rgb_to_lab(lcolor).reshape(-1, 3), workers=-1)
    out[lmask] = lpal[lidx.reshape(h, w)][lmask]

    # 背景：高清图上用“覆盖率”做软 alpha，再面积下采样。
    # 纯白连通区 alpha=0；距背景 3px 内的抗锯齿带按与白的接近程度给部分覆盖，
    # 这样发梢等细结构不会留下一圈半白。
    from scipy.ndimage import binary_dilation, distance_transform_edt

    fa = np.array(front)
    wmin = fa.min(axis=2)
    near_hi = wmin > 245
    lab_hi, _ = label(near_hi)
    border_hi = np.unique(np.r_[lab_hi[0], lab_hi[-1], lab_hi[:, 0], lab_hi[:, -1]])
    bg_hi = np.isin(lab_hi, border_hi[border_hi > 0])
    dist = distance_transform_edt(~bg_hi)
    zone = (~bg_hi) & (dist <= 3)
    alpha_hi = np.ones(wmin.shape, dtype=np.float32)
    alpha_hi[bg_hi] = 0.0
    alpha_hi[zone] = np.clip((250.0 - wmin[zone]) / 70.0, 0.0, 1.0)
    alpha_small = np.array(Image.fromarray((alpha_hi * 255).astype(np.uint8)).resize((w, h), Image.BOX)) / 255.0
    fg = alpha_small > 0.5
    bg = ~fg

    # 边缘去色污染：把外圈颜色替换为最近的内部颜色，消除白色渗入
    ring = binary_dilation(bg, iterations=2) & fg
    core = fg & (~binary_dilation(bg, iterations=3))
    if core.any():
        inds = distance_transform_edt(~core, return_indices=True)[1]
        out[ring] = out[inds[0][ring], inds[1][ring]]
        # 深色结构外缘的浅色像素必是抗锯齿：内部是深色而自己是浅色，直接去掉
        inner = out[inds[0], inds[1]]
        fringe = ring & (out.min(axis=2) > 200) & (inner.min(axis=2) < 190)
        # 深色区域（头发）外缘：只要 5×5 邻域整体偏暗，浅色像素就按抗锯齿处理
        loc = uniform_filter(out.astype(np.float64), size=(5, 5, 1))
        fringe |= ring & (out.min(axis=2) > 190) & (loc.min(axis=2) < 150)
        fg &= ~fringe
        bg = ~fg
        ring = binary_dilation(bg, iterations=2) & fg

    # 清掉贴着背景的浅色小碎块（发梢抗锯齿残点）
    pale = out.min(axis=2) > 200
    lab2, _ = label(fg & pale)
    sizes = np.bincount(lab2.ravel())
    small = np.isin(lab2, np.flatnonzero((sizes < 12) & (np.arange(len(sizes)) > 0)))
    small &= binary_dilation(bg, iterations=1)
    fg &= ~small
    bg = ~fg

    rgba = np.dstack([out, np.where(bg, 0, 255)]).astype(np.uint8)
    img = Image.fromarray(rgba, "RGBA")
    img.save(ROOT / "pc98" / "pc98_v7_tachie_rgba.png")

    # 索引 0 透明
    colors, inv = np.unique(out.reshape(-1, 3), axis=0, return_inverse=True)
    idx_map = inv.reshape(h, w) + 1
    idx_map[bg] = 0
    pal_idx = np.vstack([[0, 0, 0], colors]).astype(np.uint8)
    pimg = Image.fromarray(idx_map.astype(np.uint8), "P")
    flat_pal = pal_idx.reshape(-1).tolist()
    flat_pal += [0] * (768 - len(flat_pal))
    pimg.putpalette(flat_pal[:768])
    pimg.save(ROOT / "pc98" / "pc98_v7_tachie_indexed.png", transparency=0)

    # 预览：640×640 灰底
    prev = Image.new("RGB", (640, 640), (92, 96, 104))
    prev.paste(img, ((640 - w) // 2, 640 - h), img)
    prev.save(ROOT / "pc98" / "pc98_v7_tachie_preview.png")

    print("front crop", front.size, "-> sprite", (w, h), "colors", len(colors),
          "lines", round(lmask.mean() * 100, 1), "%", "partner", round(use_partner.mean() * 100, 1), "%")
    alpha = rgba[..., 3]
    halo = (alpha > 0) & (out.min(axis=2) > 228) & (np.ptp(out, axis=2) < 12)
    print("opaque %", round((alpha > 0).mean() * 100, 1), "pale opaque %", round(halo.mean() * 100, 2))


if __name__ == "__main__":
    main()
