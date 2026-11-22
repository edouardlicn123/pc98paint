# -*- coding: utf-8 -*-
"""PC-98 16 色槽位系统。

12 个固定核心槽 + 最多 4 个弹性槽，总数不超过 16。
所有颜色按 RGB 各 4bit 吸附（17 的倍数）。

用法：
    python palette98.py --list
    python palette98.py --build skin_mid,pale_yellow,blush,navy_dark --out out.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.ndimage import binary_dilation, label

# 12 色固定核心：四张参考图逐色求交集的稳定结果
CORE = {
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "skin_light": (255, 221, 187),
    "red": (238, 85, 102),
    "red_dark": (102, 51, 51),
    "brown": (136, 85, 68),
    "gold": (238, 187, 102),
    "green": (119, 170, 102),
    "blue": (68, 68, 136),
    "lavender": (136, 119, 221),
    "gray_green_light": (170, 187, 170),
    "gray_green_dark": (102, 119, 102),
}

# 弹性槽：每张图最多取 4 个
FLEX = {
    "skin_mid": (221, 153, 119),
    "skin_mid_alt": (204, 136, 102),
    "pale_yellow": (221, 221, 187),
    "sky": (187, 238, 255),
    "blush": (255, 170, 170),
    "orange_brown": (204, 136, 85),
    "dark_green": (51, 68, 51),
    "brick_red": (153, 68, 68),
    "navy_dark": (34, 51, 85),
    "navy_mid": (34, 68, 119),
}

DESC = {
    "black": "线稿/瞳孔/最深阴影",
    "white": "高光/眼白/白色材质",
    "skin_light": "皮肤亮部",
    "red": "红/粉主色",
    "red_dark": "红系暗部",
    "brown": "棕发/皮革/木",
    "gold": "金发/饰物/纽扣",
    "green": "绿衣/植物",
    "blue": "蓝衣/眼睛",
    "lavender": "蓝的高光/眼高光",
    "gray_green_light": "背景亮部",
    "gray_green_dark": "背景暗部/布料暗部",
    "skin_mid": "皮肤中间调",
    "skin_mid_alt": "皮肤中间调（偏橙）",
    "pale_yellow": "背景墙/白布暗部",
    "sky": "天空/冷高光",
    "blush": "腮红/唇",
    "orange_brown": "橙棕发",
    "dark_green": "深绿背景",
    "brick_red": "第二角色的红",
    "navy_dark": "深蓝发/制服暗部",
    "navy_mid": "制服中间调（与 navy_dark 组成两档）",
}

MAX_COLORS = 16


def snap17(color):
    """吸附到 RGB 各 4bit（17 的倍数）。"""
    return tuple(int(np.clip(round(v / 17.0) * 17.0, 0, 255)) for v in color)


def build(flex_names):
    """12 核心 + 指定弹性槽，返回 [(name, rgb), ...]。"""
    unknown = [n for n in flex_names if n not in FLEX]
    if unknown:
        raise ValueError(f"未知弹性槽: {unknown}")
    if len(flex_names) > MAX_COLORS - len(CORE):
        raise ValueError(f"弹性槽最多 {MAX_COLORS - len(CORE)} 个")
    out = [(n, snap17(c)) for n, c in CORE.items()]
    out += [(n, snap17(FLEX[n])) for n in flex_names]
    assert len(out) <= MAX_COLORS
    assert len({c for _, c in out}) == len(out), "槽位颜色重复"
    return out


def palette_array(slots):
    return np.array([c for _, c in slots], dtype=np.uint8)


def srgb_to_linear(c):
    c = np.asarray(c, dtype=np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def rgb_to_lab(rgb):
    """sRGB(D65) -> CIELAB，输入形状 (...,3)。"""
    lin = srgb_to_linear(rgb)
    m = np.array([
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ])
    xyz = lin @ m.T
    xyz = xyz / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16.0 / 116.0)
    return np.stack([
        116.0 * f[..., 1] - 16.0,
        500.0 * (f[..., 0] - f[..., 1]),
        200.0 * (f[..., 1] - f[..., 2]),
    ], axis=-1)


def nearest(rgb, slots):
    """返回 (索引, LAB 距离)。"""
    pal = palette_array(slots)
    d = np.linalg.norm(rgb_to_lab(np.asarray(rgb, float)) - rgb_to_lab(pal), axis=-1)
    return int(np.argmin(d)), float(np.min(d))


def rgb_to_hsv(rgb):
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    mx, mn = c.max(-1), c.min(-1)
    diff = mx - mn
    h = np.zeros_like(mx)
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    mask = diff > 1e-9
    idx = mask & (mx == r)
    h[idx] = ((g[idx] - b[idx]) / diff[idx]) % 6
    idx = mask & (mx == g)
    h[idx] = (b[idx] - r[idx]) / diff[idx] + 2
    idx = mask & (mx == b)
    h[idx] = (r[idx] - g[idx]) / diff[idx] + 4
    h = (h * 60.0) % 360.0
    s = np.where(mx > 0, diff / np.maximum(mx, 1e-9), 0.0)
    return h, s, mx


SKIN_COLORS = {
    (255, 221, 187),
    (221, 153, 119),
    (204, 136, 102),
    (255, 170, 170),
}


def skin_mask(rgb):
    """浅肤色像素：H 5–45、S 0.06–0.50、V ≥ 0.70。"""
    h, s, v = rgb_to_hsv(rgb)
    return (h >= 5) & (h <= 45) & (s >= 0.06) & (s <= 0.50) & (v >= 0.70)


def assign(rgb, pal, skin_hint=True, highlight_hint=True):
    """最近色分配；肤色与发高光做定向修正。"""
    pal = np.asarray(pal, dtype=np.uint8)
    lab = rgb_to_lab(pal)
    src = np.asarray(rgb, dtype=np.float64)
    hh, ww = src.shape[:2]
    flat = src.reshape(-1, 3)
    d = np.linalg.norm(rgb_to_lab(flat)[:, None, :] - lab[None, :, :], axis=-1)
    idx = d.argmin(1)

    if skin_hint:
        skin_idx = [i for i, c in enumerate(pal) if tuple(int(x) for x in c) in SKIN_COLORS]
        if skin_idx:
            m = skin_mask(flat)
            if m.any():
                sub = d[m][:, skin_idx]
                idx[m] = np.array(skin_idx)[sub.argmin(1)]

    if highlight_hint:
        # 蓝发附近的奶油色高光改判为淡紫，避免头发上出现浅黄空洞
        lav = [i for i, c in enumerate(pal) if tuple(int(x) for x in c) == (136, 119, 221)]
        if lav:
            h, s, v = rgb_to_hsv(flat)
            blue = ((h >= 200) & (h <= 280) & (s >= 0.35)).reshape(hh, ww)
            near_blue = binary_dilation(blue, iterations=6).reshape(-1)
            cand = (v >= 0.85) & (s >= 0.05) & (s <= 0.32) & (h >= 40) & (h <= 80) & near_blue
            if cand.any():
                idx[cand] = lav[0]
    return idx.reshape(hh, ww)


def fix_white_holes(idx, pal, max_size=600):
    """把被蓝色包围、且不贴黑线的白色小岛并入淡紫。

    用于清掉蓝发里残留的白色高光洞；眼白紧贴黑线、衣领面积大，都会被跳过。
    """
    pal = np.asarray(pal, dtype=np.uint8)
    white = [i for i, c in enumerate(pal) if tuple(int(x) for x in c) == (255, 255, 255)]
    lav = [i for i, c in enumerate(pal) if tuple(int(x) for x in c) == (136, 119, 221)]
    black = [i for i, c in enumerate(pal) if tuple(int(x) for x in c) == (0, 0, 0)]
    if not white or not lav or not black:
        return idx

    h, s, _ = rgb_to_hsv(pal.astype(np.float64))
    blueish = (h >= 200) & (h <= 280) & (s >= 0.30)
    blue_idx = set(int(i) for i in np.where(blueish)[0])
    black_idx = black[0]

    mask = idx == white[0]
    lab, n = label(mask)
    out = idx.copy()
    for i in range(1, n + 1):
        comp = lab == i
        if comp.sum() > max_size:
            continue
        ring = binary_dilation(comp, iterations=2) & ~comp
        vals = idx[ring]
        if vals.size == 0:
            continue
        blue_frac = np.mean([int(v) in blue_idx for v in vals])
        black_frac = np.mean(vals == black_idx)
        if blue_frac >= 0.45 and black_frac < 0.20:
            out[comp] = lav[0]
    return out


def save(slots, path, note=""):
    data = {
        "note": note,
        "count": len(slots),
        "colors": [list(c) for _, c in slots],
        "slots": [{"name": n, "rgb": list(c), "desc": DESC.get(n, "")} for n, c in slots],
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [tuple(c) for c in data["colors"]]


def _print_table():
    print("== 12 色固定核心 ==")
    for n, c in CORE.items():
        print(f"  {n:18s} {str(c):18s} {DESC[n]}")
    print("== 弹性槽（每图≤4） ==")
    for n, c in FLEX.items():
        print(f"  {n:18s} {str(c):18s} {DESC[n]}")


def main():
    ap = argparse.ArgumentParser(description="PC-98 16 色槽位系统")
    ap.add_argument("--list", action="store_true", help="列出核心与弹性槽")
    ap.add_argument("--build", default="", help="逗号分隔的弹性槽名")
    ap.add_argument("--out", default="", help="输出 JSON 路径")
    args = ap.parse_args()

    if args.list or not args.build:
        _print_table()
        return

    names = [n.strip() for n in args.build.split(",") if n.strip()]
    slots = build(names)
    print(f"共 {len(slots)} 色")
    for n, c in slots:
        print(f"  {n:18s} {str(c):18s} {DESC.get(n, '')}")
    if args.out:
        save(slots, args.out)
        print("saved", args.out)


if __name__ == "__main__":
    main()
