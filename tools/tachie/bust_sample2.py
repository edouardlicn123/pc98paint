# -*- coding: utf-8 -*-
"""640×400 PC-98 头部样张 v2。

v2 修正：
- 取消 Floyd–Steinberg，改为硬阶 + 仅在色阶边界做棋盘交错
- 合并近似色，消除白/白之间的碎点
- 线稿细化到 1px（Zhang-Suen）
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance
from scipy.ndimage import binary_dilation, binary_propagation
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[2]
LIB = Path(__file__).resolve().parents[1] / "lib"
SRC = ROOT / "_work" / "pc98_src"
sys.path.insert(0, str(LIB))
import pc98_sprite_v7 as v7  # noqa: E402

W, H = 640, 400

# 参考图规则手工色板：全部落在 17 的倍数上，暗部暖色，不用中性灰
PALETTE = np.array([
    [0, 0, 0],          # 线
    [17, 17, 34],       # 最暗
    [17, 34, 68],       # 发暗
    [34, 68, 119],      # 发中
    [51, 85, 136],      # 发主
    [85, 102, 153],     # 发亮
    [68, 51, 102],      # 发紫
    [238, 221, 187],    # 发高光奶油
    [221, 204, 170],    # 发高光次
    [68, 85, 153],      # 制服亮
    [34, 68, 136],      # 制服主
    [17, 51, 102],      # 制服暗
    [255, 255, 255],    # 白
    [221, 204, 204],    # 白暗暖粉灰
    [187, 170, 170],    # 白深影
    [255, 238, 221],    # 肤亮
    [238, 204, 187],    # 肤中
    [204, 170, 170],    # 肤影
    [170, 119, 119],    # 肤深
    [221, 85, 102],     # 领巾亮
    [187, 51, 85],      # 领巾主
    [136, 34, 68],      # 领巾暗
], dtype=np.uint8)


def warm_gray_fix(rgb):
    a = rgb.astype(np.float64)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    low = ((a.max(2) - a.min(2)) < 18) & (a.min(2) < 245)
    light = low & (lum > 95)
    dark = low & (lum <= 95)
    out = a.copy()
    warm = np.dstack([lum * 1.00, lum * 0.92, lum * 0.90])
    cool = np.dstack([lum * 0.86, lum * 0.80, lum * 1.06])
    out[light] = a[light] * 0.35 + warm[light] * 0.65
    out[dark] = a[dark] * 0.40 + cool[dark] * 0.60
    return np.clip(out, 0, 255).astype(np.uint8)


def snap17(pal):
    return np.clip(np.round(pal / 17.0) * 17.0, 0, 255).astype(np.uint8)


def merge(pal, used, thresh=30):
    order = np.argsort(-used)
    out = []
    for i in order:
        c = pal[i].astype(np.int32)
        if all(np.abs(c - m).max() > thresh for m in out):
            out.append(c)
    out = np.array(out, dtype=np.uint8)
    for must in ([0, 0, 0], [255, 255, 255]):
        if not (out == must).all(1).any():
            out = np.vstack([out, must])
    return out


def boundary_dither(idx, allowed=None):
    h, w = idx.shape
    diff = np.zeros((h, w), bool)
    for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0)):
        nb = np.roll(idx, (-dy, -dx), axis=(0, 1))
        diff |= nb != idx
    diff = binary_dilation(diff, iterations=1)
    yy, xx = np.mgrid[0:h, 0:w]
    checker = ((xx + yy) % 2) == 0
    new = idx.copy()
    done = np.zeros_like(diff)
    for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0)):
        nb = np.roll(idx, (-dy, -dx), axis=(0, 1))
        sel = diff & checker & (~done) & (nb != idx)
        if allowed is not None:
            sel &= allowed[idx, nb]
        new[sel] = nb[sel]
        done |= sel
    return new


def zhang_suen(mask):
    img = mask.astype(np.uint8)
    while True:
        changed = False
        for step in (0, 1):
            p = np.pad(img, 1)
            P2, P3, P4 = p[:-2, 1:-1], p[:-2, 2:], p[1:-1, 2:]
            P5, P6, P7 = p[2:, 2:], p[2:, 1:-1], p[2:, :-2]
            P8, P9 = p[1:-1, :-2], p[:-2, :-2]
            B = P2 + P3 + P4 + P5 + P6 + P7 + P8 + P9
            seq = [P2, P3, P4, P5, P6, P7, P8, P9, P2]
            A = sum(((seq[i] == 0) & (seq[i + 1] == 1)).astype(np.uint8) for i in range(8))
            m = (img == 1) & (B >= 2) & (B <= 6) & (A == 1)
            if step == 0:
                m &= (P2 * P4 * P6 == 0) & (P4 * P6 * P8 == 0)
            else:
                m &= (P2 * P4 * P8 == 0) & (P2 * P6 * P8 == 0)
            if m.any():
                img[m] = 0
                changed = True
        if not changed:
            break
    return img.astype(bool)


def background_mask(src):
    a = np.array(src).astype(np.int16)
    near = a.min(2) >= 235
    seed = np.zeros_like(near)
    seed[0, :], seed[-1, :] = near[0, :], near[-1, :]
    seed[:, 0], seed[:, -1] = near[:, 0], near[:, -1]
    return binary_propagation(seed, mask=near)


def main():
    src = Image.open(SRC / "akira_bust_hi.jpg").convert("RGB")
    bg_hi = background_mask(src)

    mid = src.resize((W * 2, H * 2), Image.BOX)
    color = mid.resize((W, H), Image.BOX)
    color = ImageEnhance.Color(color).enhance(1.08)
    rgb = warm_gray_fix(np.array(color))
    pal = PALETTE

    flat_rgb = rgb.reshape(-1, 3)
    _, idx = cKDTree(v7.rgb_to_lab(pal)).query(v7.rgb_to_lab(flat_rgb), workers=-1)
    idx = idx.reshape(H, W)
    idx = boundary_dither(idx)
    fills = pal[idx]

    lmask, _ = v7.line_layer(mid, (W, H))
    lmask = zhang_suen(lmask)
    fills[lmask] = (0, 0, 0)

    bg = np.array(Image.fromarray((bg_hi * 255).astype(np.uint8)).resize((W, H), Image.BOX)) > 127
    alpha = np.where(bg, 0, 255).astype(np.uint8)
    out = Image.fromarray(np.dstack([fills, alpha]).astype(np.uint8), "RGBA")

    outdir = ROOT / "output"
    out.save(outdir / "akira_bust_640x400.png")
    white = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    white.alpha_composite(out)
    white.convert("RGB").save(outdir / "akira_bust_640x400_white.png")
    white.convert("RGB").save(outdir / "akira_bust_640x400.jpg", quality=97, subsampling=0)

    arr = fills.astype(np.int16)
    chroma = arr.max(2) - arr.min(2)
    lum = 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
    midgray = ((chroma < 12) & (lum > 20) & (lum < 235) & (~bg)).sum()
    blk = np.all(fills == 0, 2)
    runs = []
    for y in range(H):
        c = 0
        for v in blk[y]:
            if v:
                c += 1
            elif c:
                runs.append(c)
                c = 0
    print("palette", len(pal), "used", len(np.unique(fills.reshape(-1, 3), axis=0)))
    print("mid_gray_px", int(midgray), "black_px", int(blk.sum()))
    print("1px_runs", runs.count(1), "2px_runs", runs.count(2), "3px", runs.count(3))


if __name__ == "__main__":
    main()
