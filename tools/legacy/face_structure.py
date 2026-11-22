# -*- coding: utf-8 -*-
"""面部结构绘制器（特征锚定版）：先定位眼线，再放少量结构面；不做整条下颌带。

用法：
    python tools/legacy/face_structure.py --front _work/pc98_src/akira_front.png \
        --spec characters/akira/spec.json --out _work/pc98_src/akira_front_faceA.png
"""
import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
import repair  # noqa: E402
import schema  # noqa: E402


def skin_mask(a):
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    return (R > 120) & (R > G) & (G > B - 12) & ((R - B) > 10) & ((R - B) < 120)


def build(front, spec, k=6):
    a = np.array(front).astype(np.float32)
    h, w = a.shape[:2]
    sm = skin_mask(a)
    head = sm.copy()
    head[int(h * 0.32):] = False
    ys, xs = np.where(head)
    if len(ys) < 200:
        raise SystemExit("未找到面部区域")

    lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    # 眼线：贴近皮肤的暗像素（睫毛/虹膜），取行中位数
    dark = (lum < 85) & binary_dilation(head, iterations=6)
    ry = np.flatnonzero(dark.any(axis=1))
    eye_y = int(np.median(ry)) if len(ry) else int(ys.min() + 0.45 * (ys.max() - ys.min()))

    row = np.flatnonzero(sm[eye_y]) if eye_y < h else np.array([])
    if len(row) < 20:
        row = xs
    x0, x1 = int(row.min()), int(row.max())
    face_w = max(x1 - x0, 1)
    cx = (x0 + x1) // 2

    # 下巴：眼睛以下、皮肤行宽骤减处
    chin = ys.max()
    for y in range(eye_y, ys.max()):
        r = np.flatnonzero(sm[y])
        if len(r) and (r.max() - r.min()) < 0.35 * face_w:
            chin = y
            break
    face_h = max(chin - ys.min(), 1)

    pal = spec["palette"]["skin"]
    base = np.median(a[head], axis=0)
    shadow = np.array([int(pal[2][i:i + 2], 16) for i in (1, 3, 5)], np.float32)
    cream = np.array([248, 240, 220], np.float32)
    dark_col = 0.6 * base + 0.4 * shadow
    light_col = 0.8 * base + 0.2 * cream

    yy, xx = np.mgrid[0:h, 0:w]
    usable = sm & (lum > 95) & (np.ptp(a, axis=2) < 90)

    def put(mask, color, strength):
        sel = usable & mask
        if sel.any():
            a[sel] = a[sel] * (1 - strength) + np.array(color, np.float32) * strength

    top = ys.min()
    # 1) 刘海下影：发际线下 3–6% 面高
    put((yy > top + 0.005 * face_h) & (yy < top + 0.06 * face_h), dark_col, 0.35)
    # 2) 鼻侧 1–2px：从眼下到鼻底
    nose_base = eye_y + int(0.45 * (chin - eye_y))
    put((xx > cx + int(0.03 * face_w)) & (xx < cx + int(0.05 * face_w)) &
        (yy > eye_y) & (yy < nose_base), dark_col, 0.45)
    # 3) 颈：下巴以下
    put(yy > chin, dark_col, 0.5)
    # 4) 下巴受光：仅中心一小块
    put((np.abs(xx - cx) < 0.10 * face_w) & (yy > chin - 0.10 * face_h) & (yy < chin), light_col, 0.3)

    # 收束阶数，去掉抗锯齿碎色
    face_sel = sm & (yy < chin + 0.05 * face_h)
    if face_sel.sum() > 200:
        a[face_sel] = repair._kmeans(a[face_sel].astype(np.uint8), k=k)
    return Image.fromarray(a.clip(0, 255).astype(np.uint8))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--front", required=True)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--k", type=int, default=6)
    args = ap.parse_args()
    spec = schema.load(ROOT / args.spec)
    img = Image.open(ROOT / args.front).convert("RGB")
    out = build(img, spec, args.k)
    out.save(ROOT / args.out)
    print("saved", args.out, out.size)


if __name__ == "__main__":
    main()
