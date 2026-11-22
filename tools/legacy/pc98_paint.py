# -*- coding: utf-8 -*-
"""按论文 S1-S6 流程重绘立绘：
硬边分面 -> 16 色索引 -> 只在色阶交界生成过渡带 -> 点阵沿形体方向/密度分级 -> 平面区零抖动。
"""
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "_work", "pc98_src", "tachie_girl_flat.jpg")
OUT = os.path.join(ROOT, "pc98")

PALETTE = [
    (17, 17, 17),     # 0 线稿黑
    (34, 34, 68),     # 1 头发最深
    (51, 51, 102),    # 2 头发中间
    (85, 85, 136),    # 3 头发亮 / 制服深影
    (51, 68, 119),    # 4 制服暗
    (85, 102, 153),   # 5 制服中
    (119, 136, 170),  # 6 制服受光
    (153, 170, 204),  # 7 制服高光
    (255, 238, 221),  # 8 白
    (255, 221, 204),  # 9 肤色亮
    (238, 187, 170),  # 10 肤色中
    (221, 153, 136),  # 11 肤色影
    (187, 119, 102),  # 12 暖色深影
    (204, 51, 68),    # 13 缎带红
    (153, 34, 51),    # 14 缎带暗红
    (221, 204, 221),  # 15 淡紫
]
BLACK_IDX, WHITE_IDX = 0, 8
B4 = np.array([
    [0, 8, 2, 10],
    [12, 4, 14, 6],
    [3, 11, 1, 9],
    [15, 7, 13, 5],
], dtype=np.float64) / 16.0 + 1 / 32.0


def key_white(path):
    img = Image.open(path).convert("RGB")
    w, h = img.size
    for seed in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        ImageDraw.floodfill(img, seed, (255, 0, 255), thresh=26)
    arr = np.array(img)
    mask = (arr[:, :, 0] > 240) & (arr[:, :, 1] < 40) & (arr[:, :, 2] > 240)
    alpha = np.where(mask, 0, 255).astype(np.uint8)
    arr[mask] = 255
    return arr, alpha


def fit(rgb, alpha, bw=256, bh=290):
    ys, xs = np.where(alpha > 0)
    t, b, l, r = ys.min(), ys.max(), xs.min(), xs.max()
    rgb, alpha = rgb[t:b + 1, l:r + 1], alpha[t:b + 1, l:r + 1]
    h, w = alpha.shape
    s = min(bw / w, bh / h)
    nw, nh = max(1, round(w * s)), max(1, round(h * s))
    im = Image.fromarray(rgb).resize((nw, nh), Image.LANCZOS)
    am = Image.fromarray(alpha).resize((nw, nh), Image.LANCZOS)
    canvas = np.full((bh, bw, 3), 255, np.uint8)
    ca = np.zeros((bh, bw), np.uint8)
    x0, y0 = (bw - nw) // 2, bh - nh
    canvas[y0:y0 + nh, x0:x0 + nw] = np.array(im)
    ca[y0:y0 + nh, x0:x0 + nw] = np.array(am)
    return canvas, np.where(ca > 128, 255, 0).astype(np.uint8)


def box_blur(a, r=2):
    k = 2 * r + 1
    c = np.cumsum(np.pad(a, ((r + 1, r), (0, 0)), mode="edge"), axis=0)
    a = (c[k:] - c[:-k]) / k
    c = np.cumsum(np.pad(a, ((0, 0), (r + 1, r)), mode="edge"), axis=1)
    return (c[:, k:] - c[:, :-k]) / k


def dilate(mask, n=1):
    for _ in range(n):
        m = mask.copy()
        m[1:, :] |= mask[:-1, :]
        m[:-1, :] |= mask[1:, :]
        m[:, 1:] |= mask[:, :-1]
        m[:, :-1] |= mask[:, 1:]
        mask = m
    return mask


def main():
    rgb, alpha = key_white(SRC)
    rgb, alpha = fit(rgb, alpha)
    h, w, _ = rgb.shape
    pal = np.array(PALETTE, dtype=np.float64)
    lum = pal @ np.array([0.299, 0.587, 0.114])
    f = rgb.astype(np.float64)
    # 去掉缩放带来的白边：近白的不透明边缘像素取内侧邻色
    acc = np.zeros_like(f)
    cnt = np.zeros((h, w))
    for _ in range(3):
        m = alpha > 0
        acc[:] = 0
        cnt[:] = 0
        for dy, dx in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            sf = np.roll(f, (dy, dx), axis=(0, 1))
            sm = np.roll(m, (dy, dx), axis=(0, 1))
            acc += np.where(sm[..., None], sf, 0)
            cnt += sm
        halo = m & (cnt > 0) & (cnt < 4)
        f[halo] = acc[halo] / cnt[halo][..., None]

    # 残余白边：靠近透明区的近白像素直接裁掉
    trans = ~(alpha > 0)
    td = np.full((h, w), 99, np.float64)
    td[trans] = 0
    cur = trans.copy()
    for k in range(1, 3):
        nxt = dilate(cur, 1) & (td == 99)
        td[nxt] = k
        cur |= nxt
    sat = f.max(axis=2) - f.min(axis=2)
    alpha[(sat < 70) & (f.min(axis=2) > 170) & (f[..., 2] >= f[..., 0]) & (td <= 5)] = 0

    # S1-S3：硬边分面（最近色 = 一个调色板索引）
    d = ((f[..., None, :] - pal[None, None, :, :]) ** 2).sum(-1)
    idx = d.argmin(-1)
    d2 = d.copy()
    np.put_along_axis(d2, idx[..., None], 1e18, axis=-1)
    idx2 = d2.argmin(-1)

    # S4：找色阶交界，只保留“有意义”的边界（排除线稿黑/白、对比过强）
    border = np.zeros((h, w), bool)
    for dy, dx in [(1, 0), (0, 1)]:
        diff = idx != np.roll(idx, (dy, dx), axis=(0, 1))
        border |= diff
        border |= np.roll(diff, (-dy, -dx), axis=(0, 1))
    ld = np.abs(lum[idx] - lum[idx2])
    usable = (ld > 18) & (ld < 80)
    usable &= (idx != BLACK_IDX) & (idx2 != BLACK_IDX)
    usable &= (idx != WHITE_IDX) & (idx2 != WHITE_IDX)
    border &= usable

    # 过渡带：暗面一侧宽（点阵生长进阴影），受光一侧只留 1px
    sign = np.where(lum[idx] < lum[idx2], 1.0, -1.0)
    Rdark, Rlight = 5, 1
    dist = np.full((h, w), 99, np.float64)
    dist[border] = 0
    cur = border.copy()
    for k in range(1, Rdark + 1):
        nxt = dilate(cur, 1) & (dist == 99)
        dist[nxt] = k
        cur |= nxt
    band = (((dist <= Rdark) & (sign > 0)) | ((dist <= Rlight) & (sign < 0))) & (alpha > 0)

    # S5：用平滑后的结构方向决定点阵走向（切线方向）
    L = f @ np.array([0.299, 0.587, 0.114])
    Ls = box_blur(L, 2)
    gx = np.roll(Ls, -1, 1) - np.roll(Ls, 1, 1)
    gy = np.roll(Ls, -1, 0) - np.roll(Ls, 1, 0)
    ang = np.arctan2(gy, gx) + np.pi / 2          # 切线
    c2 = box_blur(np.cos(2 * ang), 2)
    s2 = box_blur(np.sin(2 * ang), 2)
    ang = 0.5 * np.arctan2(s2, c2)
    ang = np.round(ang / (np.pi / 4)) * (np.pi / 4)  # 吸附到 0/45/90/135

    # 密度 t：越靠暗面越大；只取 25/50/75 三档
    t = 0.5 + sign * np.minimum(dist, Rdark) / (2 * (Rdark + 1))
    t = np.clip(t, 0.14, 0.86)
    t = np.round(t * 4) / 4

    yy, xx = np.mgrid[0:h, 0:w]
    u = xx * np.cos(ang) + yy * np.sin(ang)
    v = -xx * np.sin(ang) + yy * np.cos(ang)
    ui = np.floor(u).astype(int) % 4
    vi = np.floor(v).astype(int) % 2
    # 沿形体切线方向成组：25% 隔行点、50% 棋盘、75% 反相
    p25 = (vi == 0) & (ui == 0)
    p50 = ((ui + vi) % 2) == 0
    level = np.round(t * 4) / 4
    use = band & np.where(level <= 0.25, p25, np.where(level >= 0.75, ~p25, p50))

    dark_id = np.where(lum[idx] < lum[idx2], idx, idx2)
    light_id = np.where(lum[idx] < lum[idx2], idx2, idx)
    out = pal[idx].astype(np.uint8)
    out[band & ~use] = pal[light_id][band & ~use].astype(np.uint8)
    out[use] = pal[dark_id][use].astype(np.uint8)
    # 非过渡带保持原分面，保证平面零噪点
    out[~band] = pal[idx][~band].astype(np.uint8)
    out[alpha == 0] = 255

    rgba = np.concatenate([out, alpha[..., None]], axis=2).astype(np.uint8)
    Image.fromarray(rgba, "RGBA").save(os.path.join(OUT, "pc98_tachie_v2.png"))

    # 局部放大：左袖 + 胸前褶皱
    crop = Image.fromarray(rgba[120:290, 0:150], "RGBA").resize((600, 680), Image.NEAREST)
    chk = Image.new("RGB", (620, 700), (70, 70, 80))
    dr = ImageDraw.Draw(chk)
    for y in range(0, 700, 20):
        for x in range(0, 620, 20):
            if (x // 20 + y // 20) % 2 == 0:
                dr.rectangle([x, y, x + 19, y + 19], fill=(100, 100, 115))
    chk.paste(crop, (10, 10), crop)
    chk.save(os.path.join(OUT, "pc98_tachie_v2_zoom.png"))

    used = len(np.unique(out[alpha > 0].reshape(-1, 3), axis=0))
    print("sprite colors:", used, "| dither px:", int(use.sum()), "/", int((alpha > 0).sum()),
          "| band px:", int(band.sum()))


if __name__ == "__main__":
    main()
