# -*- coding: utf-8 -*-
"""B 线精修：覆盖率 alpha、外缘 1px 描线、按边界交错、提高彩度。"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance
from scipy.ndimage import binary_dilation, distance_transform_edt, label, uniform_filter
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import pc98_sprite_v7 as v7  # noqa: E402


def partner_keep_chroma(rgb, deg=30.0):
    lab = v7.rgb_to_lab(rgb)
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    C = np.hypot(a, b)
    h = np.degrees(np.arctan2(b, a))
    diff = (np.where(L < 50, 285.0, 55.0) - h + 180.0) % 360.0 - 180.0
    h2 = np.radians(h + np.clip(diff, -deg, deg))
    return np.clip(v7.lab_to_rgb(np.stack([L, C * np.cos(h2), C * np.sin(h2)], -1)), 0, 255).astype(np.uint8)


def main():
    im = Image.open(ROOT / "_work" / "pc98_src" / "girl_full_hi.jpg").convert("RGB")
    a = np.array(im)
    mask = (a < 245).any(axis=2)
    rows, cols = np.flatnonzero(mask.sum(1) > 3), np.flatnonzero(mask.sum(0) > 3)
    im = im.crop((cols[0], rows[0], cols[-1] + 1, rows[-1] + 1))

    h = 640
    w = round(im.width * h / im.height)
    if w > 300:
        w, h = 300, round(im.height * 300 / im.width)

    mid = im.resize((w * 2, h * 2), Image.BOX)
    color = mid.resize((w, h), Image.BOX)
    color = ImageEnhance.Color(color).enhance(1.15)  # 轻微提彩度
    lmask, lcolor = v7.line_layer(mid, (w, h))

    q = color.quantize(colors=128, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
    base = np.array(q.getpalette()[: 128 * 3], dtype=np.uint8).reshape(-1, 3)
    part = partner_keep_chroma(base)
    pal = np.vstack([base, part])

    rgb = np.array(color)
    dist, idx = cKDTree(v7.rgb_to_lab(pal)).query(v7.rgb_to_lab(rgb).reshape(-1, 3), workers=-1)
    dist = dist.reshape(h, w)
    idx = idx.reshape(h, w)

    # 只在边界带内交错，平坦区保持实色
    lum = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    gy, gx = np.gradient(lum)
    band = binary_dilation(np.hypot(gx, gy) > 16, iterations=1) & (~lmask)
    yy, xx = np.mgrid[0:h, 0:w]
    bay = v7.BAYER[yy % 8, xx % 8]
    chroma = np.ptp(rgb, axis=2)
    dither = band & (bay < 0.5) & (idx < len(base)) & (chroma < 60) & (dist < 40)
    out_idx = idx.copy()
    out_idx[dither] = idx[dither] + len(base)
    out = pal[out_idx]

    lq = Image.fromarray(lcolor).quantize(colors=16, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
    lpal = np.array(lq.getpalette()[:48], dtype=np.uint8).reshape(-1, 3)
    _, lidx = cKDTree(v7.rgb_to_lab(lpal)).query(v7.rgb_to_lab(lcolor).reshape(-1, 3), workers=-1)
    out[lmask] = lpal[lidx.reshape(h, w)][lmask]

    # 覆盖率 alpha
    fa = np.array(im)
    wmin = fa.min(axis=2)
    near = wmin > 245
    lab, _ = label(near)
    border = np.unique(np.r_[lab[0], lab[-1], lab[:, 0], lab[:, -1]])
    bg_hi = np.isin(lab, border[border > 0])
    dt = distance_transform_edt(~bg_hi)
    zone = (~bg_hi) & (dt <= 3)
    alpha_hi = np.ones(wmin.shape, np.float32)
    alpha_hi[bg_hi] = 0
    alpha_hi[zone] = np.clip((250.0 - wmin[zone]) / 70.0, 0, 1)
    cov = np.array(Image.fromarray((alpha_hi * 255).astype(np.uint8)).resize((w, h), Image.BOX)) / 255.0
    fg = cov > 0.5

    # 区分“高光”与“白边”：
    #   白边 = 轮廓最外 1–2px、接近中性白、且内侧是深发色；
    #   高光 = 离背景 ≥2px，或带暖色偏（奶油白，R 明显大于 B）。
    d_in = distance_transform_edt(fg)
    rim = fg & (d_in <= 1.5)
    rgb_i = out.astype(np.int16)
    pale = rgb_i.min(axis=2) > 190
    neutral = (np.ptp(rgb_i, axis=2) < 40) & (np.abs(rgb_i[..., 0] - rgb_i[..., 2]) < 18)
    warm = (rgb_i[..., 0] - rgb_i[..., 2]) > 14
    inner = fg & (d_in >= 2.5)
    inds = distance_transform_edt(~inner, return_indices=True)[1]
    inner_col = out[inds[0], inds[1]]
    inner_dark = inner_col.min(axis=2) < 110
    dark_ctx = uniform_filter(((out.min(axis=2) < 100) & fg).astype(np.float64), size=5)
    hair_zone = (yy < int(h * 0.45)) & (dark_ctx > 0.30)  # 只处理头发区
    fringe = rim & pale & neutral & (~warm) & inner_dark & hair_zone
    out[fringe] = inner_col[fringe]

    # 若外圈仍是浅色，直接收掉这一圈；再由描线补回硬边（仅头发区）
    removed = 0
    for _ in range(3):
        d_in = distance_transform_edt(fg)
        rim = fg & (d_in <= 1.5)
        pale_rim = rim & (out.min(axis=2) > 185) & hair_zone
        if not pale_rim.any():
            break
        removed += int(pale_rim.sum())
        fg &= ~pale_rim

    # 外缘 1px 描线：沿轮廓压深，保留色相
    edge = fg & binary_dilation(~fg, iterations=1) & (~lmask)
    out[edge] = (out[edge] * 0.45).astype(np.uint8)

    rgba = np.dstack([out, np.where(fg, 255, 0)]).astype(np.uint8)
    img = Image.fromarray(rgba, "RGBA")
    img.save(ROOT / "pc98" / "pc98_b2_tachie.png")
    prev = Image.new("RGB", (640, 640), (92, 96, 104))
    prev.paste(img, ((640 - w) // 2, 640 - h), img)
    prev.save(ROOT / "pc98" / "pc98_b2_preview.png")
    print("size", (w, h), "colors", len(np.unique(out[fg], axis=0)),
          "lines", round(lmask.mean() * 100, 1), "%", "dither", round(dither.mean() * 100, 1), "%",
          "fringe fixed", int(fringe.sum()), "rim removed", removed)


main()
