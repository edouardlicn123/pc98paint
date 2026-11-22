# -*- coding: utf-8 -*-
"""把高分辨率人物图落成 ≤300×640 的索引色立绘。"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance
from scipy.ndimage import binary_dilation, binary_propagation, distance_transform_edt, label, uniform_filter
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[2]
LIB = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))
import pc98_sprite_v7 as v7  # noqa: E402


def _partner(rgb, deg=30.0):
    lab = v7.rgb_to_lab(rgb)
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    C = np.hypot(a, b)
    h = np.degrees(np.arctan2(b, a))
    diff = (np.where(L < 50, 285.0, 55.0) - h + 180.0) % 360.0 - 180.0
    h2 = np.radians(h + np.clip(diff, -deg, deg))
    return np.clip(v7.lab_to_rgb(np.stack([L, C * np.cos(h2), C * np.sin(h2)], -1)), 0, 255).astype(np.uint8)


def _crop_subject(im, thr=245):
    a = np.array(im)
    mask = (a < thr).any(axis=2)
    rows, cols = np.flatnonzero(mask.sum(1) > 3), np.flatnonzero(mask.sum(0) > 3)
    return im.crop((cols[0], rows[0], cols[-1] + 1, rows[-1] + 1))


def pixelize(src, render, out_prefix):
    im = _crop_subject(Image.open(src).convert("RGB"))
    h = render["sprite_h"]
    w = round(im.width * h / im.height)
    if w > render["sprite_w_max"]:
        w, h = render["sprite_w_max"], round(im.height * render["sprite_w_max"] / im.width)

    mid = im.resize((w * 2, h * 2), Image.BOX)
    color = ImageEnhance.Color(mid.resize((w, h), Image.BOX)).enhance(1.12)
    lmask, lcolor = v7.line_layer(mid, (w, h))

    q = color.quantize(colors=128, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
    base = np.array(q.getpalette()[: 128 * 3], dtype=np.uint8).reshape(-1, 3)
    pal = np.vstack([base, _partner(base)])
    rgb = np.array(color)
    dist, idx = cKDTree(v7.rgb_to_lab(pal)).query(v7.rgb_to_lab(rgb).reshape(-1, 3), workers=-1)
    dist = dist.reshape(h, w)
    idx = idx.reshape(h, w)

    lum = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    gy, gx = np.gradient(lum)
    band = binary_dilation(np.hypot(gx, gy) > 16, iterations=render["dither_band"]) & (~lmask)
    yy, xx = np.mgrid[0:h, 0:w]
    bay = v7.BAYER[yy % 8, xx % 8]
    chroma = np.ptp(rgb, axis=2)
    dither = band & (bay < render["dither_density"]) & (idx < len(base)) & (chroma < 60) & (dist < 40)
    out_idx = idx.copy()
    out_idx[dither] = idx[dither] + len(base)
    out = pal[out_idx]

    lq = Image.fromarray(lcolor).quantize(colors=16, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
    lpal = np.array(lq.getpalette()[:48], dtype=np.uint8).reshape(-1, 3)
    _, lidx = cKDTree(v7.rgb_to_lab(lpal)).query(v7.rgb_to_lab(lcolor).reshape(-1, 3), workers=-1)
    out[lmask] = lpal[lidx.reshape(h, w)][lmask]

    # 覆盖率 alpha。背景判定用"墨水阻挡泛洪"而不是单纯的近白连通：
    # 生成源图的背景是软渐变白（wmin 225-250），低于近白阈值的背景
    # 大片区域会被误判成前景（2026-11-21 立绘身后出现奶白色残片）。
    # 角色的深色线稿（wmin<150）是背景不可穿越的屏障，从四边泛洪
    # 即可得到真正的背景；泛洪到的都算背景，避免阈值与白袜基色冲突。
    fa = np.array(im)
    wmin = fa.min(axis=2)
    ink_hi = wmin < 150
    floodable = (wmin >= 222) & (~ink_hi)
    seed = np.zeros_like(floodable)
    seed[0, :] = floodable[0, :]
    seed[-1, :] = floodable[-1, :]
    seed[:, 0] = floodable[:, 0]
    seed[:, -1] = floodable[:, -1]
    bg_reach = binary_propagation(seed, mask=floodable)
    # 背景近旁的非深色像素（软白残片、噪点）一并归入背景；
    # 描线核心（<150）保留为前景
    dt_bg = distance_transform_edt(~bg_reach)
    bg_all = bg_reach | ((~bg_reach) & (dt_bg <= 2) & (~ink_hi))
    # 线稿内侧的封闭小白隙（刘海与脸颊之间的透缝）= 背景 glimpses；
    # 大块封闭白（白领、袜子内部）保留为前景织物
    enc = (~bg_all) & (wmin >= 222) & (~ink_hi)
    lab_e, ne = label(enc)
    for i in range(1, ne + 1):
        m = lab_e == i
        if m.sum() < 300:
            bg_all |= m
    alpha_hi = np.ones(wmin.shape, np.float32)
    alpha_hi[bg_all] = 0
    zone = (~bg_all) & (dt_bg <= 3)
    alpha_hi[zone] = np.clip((250.0 - wmin[zone]) / 70.0, 0, 1)
    cov = np.array(Image.fromarray((alpha_hi * 255).astype(np.uint8)).resize((w, h), Image.BOX)) / 255.0
    fg = cov > 0.5

    # 白边：全图范围收掉贴着背景的中性浅色抗锯齿残留（不限头发区，
    # 否则身体/四肢边缘留白边）。只做单次通过：d_in 在原始前景上算好，
    # 一次性去掉 ≤2px 的浅色边缘带。不能迭代——每轮重算 d_in 会把
    # 新暴露的浅色继续剥掉，白袜等浅色窄区域会被逐层啃穿成透明洞
    # （2026-11-21 试错）。
    rgb_i = out.astype(np.int16)
    pale = rgb_i.min(axis=2) > 190
    neutral = (np.ptp(rgb_i, axis=2) < 40) & (np.abs(rgb_i[..., 0] - rgb_i[..., 2]) < 18)
    warm = (rgb_i[..., 0] - rgb_i[..., 2]) > 14
    d_in = distance_transform_edt(fg)
    pale_rim = fg & (d_in <= 2.0) & pale & neutral & (~warm)
    fg &= ~pale_rim

    edge = fg & binary_dilation(~fg, iterations=1) & (~lmask)
    out[edge] = (out[edge] * (1 - render["line_darken"])).astype(np.uint8)

    rgba = np.dstack([out, np.where(fg, 255, 0)]).astype(np.uint8)
    img = Image.fromarray(rgba, "RGBA")
    # 压回索引色上限
    qimg = img.convert("RGB").quantize(colors=render["palette_max"], method=Image.MEDIANCUT, dither=Image.Dither.NONE)
    rgb256 = np.array(qimg.convert("RGB"))
    final = np.dstack([rgb256, rgba[..., 3]])
    out_img = Image.fromarray(final, "RGBA")
    out_png = Path(str(out_prefix) + "_tachie.png")
    out_png.parent.mkdir(parents=True, exist_ok=True)
    out_img.save(out_png)
    return out_img, {"w": w, "h": h, "line_ratio": float(lmask.mean()), "dither_ratio": float(dither.mean())}
