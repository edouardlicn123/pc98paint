# -*- coding: utf-8 -*-
"""PC-98 合成管线 v5：同明度异色相配对。

核心改动（相对 v4 的“最近配对平均”）：
- 先取原色（base），再为每个原色生成一个“明度相同、色相偏移”的伙伴色；
- 画面由 base 与 partner 交错合成，平均值回到 base，不产生明度噪点；
- 暗部伙伴偏紫（285°），亮部伙伴偏暖（55°），对应参考图的冷暖偏移；
- 图案方向来自结构张量，密度固定 45%，纯白与细线回退实色。
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from scipy.ndimage import uniform_filter

ROOT = Path(__file__).resolve().parents[2]


# ---------- 色彩空间 ----------
def srgb_to_linear(c):
    c = c.astype(np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(x):
    x = np.clip(x, 0.0, 1.0)
    c = np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)
    return np.clip(c * 255.0, 0, 255)


M = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ]
)
WHITE = np.array([0.95047, 1.0, 1.08883])


def rgb_to_lab(rgb):
    c = srgb_to_linear(rgb)
    xyz = (c @ M.T) / WHITE
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack(
        [116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])],
        axis=-1,
    )


def lab_to_rgb(lab):
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    fy = (L + 16) / 116
    fx = fy + a / 500
    fz = fy - b / 200
    f = np.stack([fx, fy, fz], axis=-1)
    xyz = np.where(f > 0.206897, f**3, (f - 16 / 116) / 7.787) * WHITE
    lin = xyz @ np.linalg.inv(M).T
    return linear_to_srgb(lin)


def lab_to_lch(lab):
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    return L, np.hypot(a, b), np.degrees(np.arctan2(b, a))


def lch_to_lab(L, C, h):
    r = np.radians(h)
    return np.stack([L, C * np.cos(r), C * np.sin(r)], axis=-1)


def partner_of(rgb):
    """明度不变，色相朝紫（暗部）或暖（亮部）偏移 20°。"""
    lab = rgb_to_lab(rgb)
    L, C, h = lab_to_lch(lab)
    target = np.where(L < 50, 285.0, 55.0)
    diff = (target - h + 180.0) % 360.0 - 180.0
    step = np.clip(diff, -25.0, 25.0)
    h2 = h + step
    C2 = C * 0.9
    out = lab_to_rgb(lch_to_lab(L, C2, h2))
    return np.clip(out, 0, 255).astype(np.uint8)


# ---------- 准备画布 ----------
def prepare(src, mode):
    img = Image.open(src).convert("RGB")
    if mode == "tachie":
        arr = np.array(img)
        arr[(arr > 244).all(axis=2)] = 255
        img = Image.fromarray(arr)
        h = 384
        w = round(img.width * h / img.height)
        img = img.resize((w, h), Image.LANCZOS)
        canvas = Image.new("RGB", (640, 400), (255, 255, 255))
        canvas.paste(img, ((640 - w) // 2, 400 - h - 8))
    else:
        img = img.crop((0, 0, int(img.height * 1.6), img.height))
        canvas = img.resize((640, 400), Image.LANCZOS)
    return canvas.filter(ImageFilter.MedianFilter(3))


# ---------- 方向场 ----------
def orientation(img):
    a = np.array(img).astype(np.float64)
    lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    gy, gx = np.gradient(lum)
    jxx = uniform_filter(gx * gx, 7)
    jyy = uniform_filter(gy * gy, 7)
    jxy = uniform_filter(gx * gy, 7)
    theta = 0.5 * np.arctan2(2 * jxy, jxx - jyy)
    coh = np.sqrt((jxx - jyy) ** 2 + 4 * jxy**2) / (jxx + jyy + 1e-6)
    phi = theta + np.pi / 2
    phi = np.where(coh < 0.15, 0.0, phi)
    sx = uniform_filter(np.cos(2 * phi), 9)
    sy = uniform_filter(np.sin(2 * phi), 9)
    return 0.5 * np.arctan2(sy, sx)


def make_bayer(n):
    if n == 1:
        return np.zeros((1, 1))
    b = make_bayer(n // 2)
    return np.block([[4 * b, 4 * b + 2], [4 * b + 3, 4 * b + 1]]) / (n * n)


BAYER = make_bayer(8)


def run(name, src, mode, n_colors, density=0.5):
    canvas = prepare(src, mode)
    rgb = np.array(canvas)

    q = canvas.quantize(colors=n_colors, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
    base = np.array(q.getpalette()[:n_colors * 3], dtype=np.uint8).reshape(-1, 3)
    part = partner_of(base)

    # 基础色分配
    from scipy.spatial import cKDTree

    _, idx = cKDTree(rgb_to_lab(base)).query(rgb_to_lab(rgb).reshape(-1, 3), workers=-1)
    idx = idx.reshape(rgb.shape[:2])
    # 先把 base 分配结果压平，去掉边缘处的孤立索引，避免“脏点”
    flat = Image.fromarray(base[idx]).filter(ImageFilter.MedianFilter(3))
    _, idx = cKDTree(rgb_to_lab(base)).query(rgb_to_lab(np.array(flat)).reshape(-1, 3), workers=-1)
    idx = idx.reshape(rgb.shape[:2])

    # 方向与阈值
    phi = orientation(canvas)
    yy, xx = np.mgrid[0 : rgb.shape[0], 0 : rgb.shape[1]]
    u = (xx * np.cos(phi) + yy * np.sin(phi)) / 2.0
    v = (-xx * np.sin(phi) + yy * np.cos(phi)) / 2.0
    th = BAYER[np.floor(v).astype(int) % 8, np.floor(u).astype(int) % 8]

    # 锚点：纯白、细黑线
    lum = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    white = (rgb > 248).all(axis=2)
    dark = lum < 60
    thin = dark & (uniform_filter(dark.astype(np.float64), 7) < 0.55)
    # 原色区域的边界也回退实色，交错只发生在区域内部
    from scipy.ndimage import maximum_filter

    edge = np.zeros_like(idx, dtype=bool)
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        edge |= np.roll(idx, (dy, dx), (0, 1)) != idx
    edge = maximum_filter(edge, 3)
    anchor = white | thin
    if mode == "scene":
        anchor |= edge

    use_partner = (th < density) & (~anchor)
    out = np.where(use_partner[..., None], part[idx], base[idx])

    res = Image.fromarray(out.astype(np.uint8), "RGB")
    out_path = ROOT / "pc98" / f"pc98_v5_{name}_640x400.png"
    out_path.parent.mkdir(exist_ok=True)
    res.save(out_path)

    if mode == "tachie":
        box = (190, 10, 460, 250)
        z = res.crop(box).resize(((box[2] - box[0]) * 3, (box[3] - box[1]) * 3), Image.NEAREST)
        z_path = ROOT / "pc98" / f"pc98_v5_{name}_zoom.png"
        z.save(z_path)

    print(
        name,
        "base:", len(base),
        "colors:", len(np.unique(out.reshape(-1, 3), axis=0)),
        "partner:", round(use_partner.mean() * 100, 1), "%",
        "saved:", out_path.name,
    )


run("tachie", ROOT / "_work" / "pc98_src" / "tachie_90s_a.jpg", "tachie", 24)
run("scene", ROOT / "_work" / "pc98_src" / "scene_corridor_a.jpg", "scene", 40)
