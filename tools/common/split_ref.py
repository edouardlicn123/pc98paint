# -*- coding: utf-8 -*-
"""把参考立绘按颈线拆成「头部」与「身体」两张图，供日后查阅。

用法：
    python tools/common/split_ref.py --src refs/proportions --out refs/characters --ids 01-24
    python tools/common/split_ref.py --src refs/proportions --out refs/characters --ids 01-24 --preview

颈线判定：24 张参考图的取景差异很大（胸像 / 半身 / 全身），纯肤色检测不可靠；
因此对 shinchou_01–24 使用人工测得的颈线比例表（下表），其余图片才走自动检测。
--preview 只画红线出检查图，不写拆分结果。
"""
import argparse
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]

# 颈线位置（占画布高度的比例），逐张人工校准：切在下巴下方、领口上沿
CUT_RATIO = {
    "01": 0.36, "02": 0.44, "03": 0.35, "04": 0.34, "05": 0.37, "06": 0.39,
    "07": 0.37, "08": 0.32, "09": 0.34, "10": 0.31, "11": 0.33, "12": 0.36,
    "13": 0.24, "14": 0.32, "15": 0.27, "16": 0.33, "17": 0.33, "18": 0.35,
    "19": 0.28, "20": 0.30, "21": 0.35, "22": 0.28, "23": 0.28, "24": 0.36,
}


def skin_mask(rgb):
    r = rgb[..., 0].astype(np.int16)
    g = rgb[..., 1].astype(np.int16)
    b = rgb[..., 2].astype(np.int16)
    return (r > 110) & (r > g + 8) & (g > b + 5) & (r - b > 25) & (r < 255)


def face_blob(rgb):
    """取最像脸（头部）的肤色连通块：不贴左右/下边界，且从画面上半部开始。"""
    h, w = rgb.shape[:2]
    m = skin_mask(rgb)
    if not m.any():
        return None
    m = ndimage.binary_closing(m, structure=np.ones((3, 3)))
    lab, n = ndimage.label(m, structure=np.ones((3, 3)))
    best, best_area = None, 0
    for i in range(1, n + 1):
        comp = lab == i
        ys, xs = np.where(comp)
        if len(ys) == 0:
            continue
        if xs.min() <= 1 or xs.max() >= w - 2 or ys.max() >= h - 2:
            continue          # 贴边的一律当背景
        if ys.min() > h * 0.50:
            continue
        if len(ys) > best_area:
            best, best_area = comp, len(ys)
    return best


def cut_row(img):
    """返回颈线 y；检测不到时退回 42% 高度。"""
    rgb = np.asarray(img.convert("RGB"))
    h = rgb.shape[0]
    face = face_blob(rgb)
    if face is None:
        return int(h * 0.42)

    ys = np.where(face.any(axis=1))[0]
    widths = face.sum(axis=1).astype(float)
    top, bottom = int(ys.min()), int(ys.max())
    peak = top + int(np.argmax(widths[top:bottom + 1]))

    # 峰值（颧骨）往下第一次收窄到峰宽 55% 以下 = 颈部
    neck = None
    for y in range(peak + 2, bottom + 1):
        if widths[y] < widths[peak] * 0.55:
            neck = y
            break
    cut = (neck if neck is not None else bottom) + int(h * 0.02)
    return int(np.clip(cut, int(h * 0.27), int(h * 0.48)))


def pick(src, ids):
    lo, hi = ids
    out = []
    for p in sorted(src.glob("*.png")):
        m = re.match(r"shinchou_(\d{2})", p.name)
        if m and lo <= int(m.group(1)) <= hi:
            out.append(p)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="refs/proportions")
    ap.add_argument("--out", default="refs/characters")
    ap.add_argument("--ids", default="01-24", help="闭区间，如 01-24")
    ap.add_argument("--preview", action="store_true", help="只出红线检查图")
    args = ap.parse_args()

    src = ROOT / args.src
    out = ROOT / args.out
    lo, hi = (int(x) for x in args.ids.split("-"))
    files = pick(src, (lo, hi))
    if not files:
        sys.exit(f"没有匹配的参考图: {src}")

    tiles = []
    for p in files:
        img = Image.open(p).convert("RGB")
        w, h = img.size
        sid = re.match(r"shinchou_(\d{2})", p.name).group(1)
        y = int(h * CUT_RATIO[sid]) if sid in CUT_RATIO else cut_row(img)
        print(f"{p.name:34s} {w}x{h}  cut={y}  ({y / h:.1%})")

        if args.preview:
            d = img.copy()
            ImageDraw.Draw(d).line([(0, y), (w, y)], fill=(255, 0, 0), width=2)
            tiles.append(d)
            continue

        out.mkdir(parents=True, exist_ok=True)
        stem = p.stem
        img.crop((0, 0, w, y)).save(out / f"{stem}_head.png")
        img.crop((0, y, w, h)).save(out / f"{stem}_body.png")

    if args.preview:
        out.mkdir(parents=True, exist_ok=True)
        for i in range(0, len(tiles), 6):
            group = tiles[i:i + 6]
            sheet = Image.new("RGB", (sum(t.width for t in group), max(t.height for t in group)), "white")
            x = 0
            for t in group:
                sheet.paste(t, (x, 0))
                x += t.width
            sheet.save(out / f"_cut_preview_{i // 6 + 1}.png")
            print("preview ->", out / f"_cut_preview_{i // 6 + 1}.png")
    else:
        print(f"已写入 {len(files) * 2} 张 -> {out}")


if __name__ == "__main__":
    main()
