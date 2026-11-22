# -*- coding: utf-8 -*-
"""PC-98 索引色绘画公共核心（无副作用，供各管线脚本 import）。

从 _work/pc98_v6.py 抽出的算法主体，所有"决定 PC-98 味道"的环节集中在此：

- srgb_to_linear / linear_to_srgb : 线性光换算（配对反解必须在线性光下进行，
  见 docs/01 总论 §2.4）
- rgb_to_lab / lab_to_rgb         : Lab 色彩空间（近色检索、色相偏移用）
- partner_of(rgb)                 : 伙伴色生成——同明度、色相偏移 ≤25°，
  暗部向紫(285°)、亮部向黄(55°)，构成 96+96=192 色配对体系
- make_bayer(n) / BAYER           : 8×8 Bayer 阈值矩阵，方向性交错的密度载体
- direction(img)                  : 结构张量方向场——交错点沿形体切线排布，
  各向同性区不转向
- line_layer(mid, target)         : 线稿层——2× 上提线、按 2×2 取最大下采样
  合成 1px 线；大片深色（影面/树冠底）不算线

依赖：numpy、Pillow、scipy。

约定（AGENTS.md 同步维护）：
- 本模块不得包含任何路径常量或模块级执行语句；
- 新的场景/立绘脚本一律 import 本模块，不得复制这些函数。
"""
import numpy as np
from PIL import Image
from scipy.ndimage import uniform_filter


# ---------- 色彩空间 ----------
def srgb_to_linear(c):
    c = np.asarray(c, dtype=np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(x):
    x = np.clip(np.asarray(x, dtype=np.float64), 0.0, 1.0)
    c = np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)
    return np.clip(c * 255.0, 0, 255)


_M = np.array([[0.4124564, 0.3575761, 0.1804375],
               [0.2126729, 0.7151522, 0.0721750],
               [0.0193339, 0.1191920, 0.9503041]])
_WHITE = np.array([0.95047, 1.0, 1.08883])


def rgb_to_lab(rgb):
    c = srgb_to_linear(rgb)
    xyz = (c @ _M.T) / _WHITE
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16,
                     500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])], axis=-1)


def lab_to_rgb(lab):
    fy = (lab[..., 0] + 16) / 116
    fx = fy + lab[..., 1] / 500
    fz = fy - lab[..., 2] / 200
    f = np.stack([fx, fy, fz], axis=-1)
    xyz = np.where(f > 0.206897, f ** 3, (f - 16 / 116) / 7.787) * _WHITE
    return linear_to_srgb(xyz @ np.linalg.inv(_M).T)


# ---------- 伙伴色 ----------
def partner_of(rgb, deg=25.0):
    """96 原色 → 96 伙伴色。输入 uint8 数组，返回 uint8。"""
    lab = rgb_to_lab(np.asarray(rgb, dtype=np.float64))
    L = lab[..., 0]
    C = np.hypot(lab[..., 1], lab[..., 2])
    h = np.degrees(np.arctan2(lab[..., 2], lab[..., 1]))
    target = np.where(L < 50, 285.0, 55.0)
    diff = (target - h + 180.0) % 360.0 - 180.0
    h2 = h + np.clip(diff, -deg, deg)
    r = np.radians(h2)
    out = lab_to_rgb(np.stack([L, C * 0.9 * np.cos(r), C * 0.9 * np.sin(r)], axis=-1))
    return np.clip(out, 0, 255).astype(np.uint8)


# ---------- Bayer 交错 ----------
def make_bayer(n):
    if n == 1:
        return np.zeros((1, 1))
    b = make_bayer(n // 2)
    return np.block([[4 * b, 4 * b + 2], [4 * b + 3, 4 * b + 1]]) / (n * n)


BAYER = make_bayer(8)


def rotated_bayer(shape, phi):
    """在旋转坐标系 (u,v) 下取 Bayer 阈值：phi 来自 direction()，
    使交错图案沿局部形体切线成组。返回与 shape 同形的阈值场。"""
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    u = xx * np.cos(phi) + yy * np.sin(phi)
    v = -xx * np.sin(phi) + yy * np.cos(phi)
    return BAYER[np.floor(v).astype(int) % 8, np.floor(u).astype(int) % 8]


# ---------- 方向场 ----------
def direction(img):
    """结构张量方向场。返回 (phi, coh)：phi 为交错排布方向，coh 为相干度。"""
    a = np.asarray(img).astype(np.float64)
    lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    gy, gx = np.gradient(lum)
    jxx = uniform_filter(gx * gx, 5)
    jyy = uniform_filter(gy * gy, 5)
    jxy = uniform_filter(gx * gy, 5)
    phi = 0.5 * np.arctan2(2 * jxy, jxx - jyy) + np.pi / 2
    coh = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / (jxx + jyy + 1e-6)
    phi = np.where(coh < 0.2, 0.0, phi)          # 各向同性区不转向
    sx = uniform_filter(np.cos(2 * phi), 7)
    sy = uniform_filter(np.sin(2 * phi), 7)
    return 0.5 * np.arctan2(sy, sx), coh


# ---------- 线稿层 ----------
def line_layer(mid, target):
    """2× 中间分辨率 → 1× 线稿。

    mid : PIL Image，target 尺寸的 2 倍
    target : (w, h) 目标分辨率
    返回 (mask, color)：mask 为 1px 线位置，color 为线色（取块内最暗）。
    大片深色不算线：frac<0.6 剔除影面、树冠底等成片暗区。
    """
    a = np.array(mid).astype(np.float64)
    lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    local = uniform_filter(lum, 3)
    edge = (lum < local - 30) | (lum < 55)
    frac = uniform_filter(edge.astype(np.float64), 7)
    edge = edge & (frac < 0.6)
    h, w = target[1], target[0]
    mask = edge.reshape(h, 2, w, 2).max(axis=(1, 3))
    blocks = a.reshape(h, 2, w, 2, 3).transpose(0, 2, 1, 3, 4).reshape(h, w, 4, 3)
    sl = 0.299 * blocks[..., 0] + 0.587 * blocks[..., 1] + 0.114 * blocks[..., 2]
    pick = sl.argmin(axis=-1)
    color = np.take_along_axis(blocks, pick[..., None, None], axis=2)[..., 0, :]
    return mask, color.astype(np.uint8)


# ---------- 索引化主流程 ----------
def index_colors(color, lmask, lcolor, n_base=96, density=0.35):
    """把 1× RGB 图索引化：96 原色 + 96 伙伴色，平坦区铺方向性交错，
    线稿色归并 16 色。返回 uint8 RGB 数组与统计 dict。"""
    color = np.asarray(color)
    q = Image.fromarray(color).quantize(colors=n_base, method=Image.MEDIANCUT,
                                        dither=Image.Dither.NONE)
    base = np.array(q.getpalette()[: n_base * 3], dtype=np.uint8).reshape(-1, 3)
    pal = np.vstack([base, partner_of(base)])

    _, idx = cKD_query(rgb_to_lab(pal.astype(np.float64)),
                       rgb_to_lab(color.astype(np.float64)).reshape(-1, 3))
    idx = idx.reshape(color.shape[:2])

    phi, _ = direction(Image.fromarray(color))
    th = rotated_bayer(color.shape[:2], phi)

    lum = 0.299 * color[..., 0].astype(float) + 0.587 * color[..., 1].astype(float) \
        + 0.114 * color[..., 2].astype(float)
    gy, gx = np.gradient(lum)
    detail = uniform_filter(np.hypot(gx, gy), 5)
    flat = (detail < 5.0) & (~lmask)
    use_partner = flat & (th < density) & (idx < n_base)
    out_idx = idx.copy()
    out_idx[use_partner] = idx[use_partner] + n_base
    out = pal[out_idx]

    lq = Image.fromarray(lcolor).quantize(colors=16, method=Image.MEDIANCUT,
                                          dither=Image.Dither.NONE)
    lpal = np.array(lq.getpalette()[:48], dtype=np.uint8).reshape(-1, 3)
    _, lidx = cKD_query(rgb_to_lab(lpal.astype(np.float64)),
                        rgb_to_lab(lcolor.astype(np.float64)).reshape(-1, 3))
    lcolor_idx = lpal[lidx.reshape(lcolor.shape[:2])]
    out[lmask] = lcolor_idx[lmask]

    stats = {"colors": int(len(np.unique(out.reshape(-1, 3), axis=0))),
             "lines_pct": round(float(lmask.mean()) * 100, 1),
             "partner_pct": round(float(use_partner.mean()) * 100, 1)}
    return out, stats


def cKD_query(pal_lab, data_lab):
    """近色检索（封装 cKDTree，便于统一替换距离实现）。"""
    from scipy.spatial import cKDTree
    _, idx = cKDTree(pal_lab).query(data_lab, workers=-1)
    return _, idx
