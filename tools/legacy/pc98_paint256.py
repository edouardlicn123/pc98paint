# -*- coding: utf-8 -*-
"""256 色期（PEGC）管线：硬边分面 + 256 索引色，不使用全图抖动。"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "_work" / "pc98_src" / "tachie_90s_a.jpg"
OUT = ROOT / "pc98"
OUT.mkdir(exist_ok=True)

CANVAS = (640, 400)
SPRITE_H = 384
MARGIN_BOTTOM = 8

img = Image.open(SRC).convert("RGB")

# 1. 压平接近纯白的背景，消除 JPEG 灰噪
arr = np.array(img)
near_white = (arr > 244).all(axis=2)
arr[near_white] = 255
img = Image.fromarray(arr)

# 2. 缩到目标高度
w, h = img.size
sprite_w = round(w * SPRITE_H / h)
img = img.resize((sprite_w, SPRITE_H), Image.LANCZOS)

# 3. 中值滤波去压缩噪点，保留硬边
img = img.filter(ImageFilter.MedianFilter(3))

# 4. 白底画布居中放置
canvas = Image.new("RGB", CANVAS, (255, 255, 255))
canvas.paste(img, ((CANVAS[0] - sprite_w) // 2, CANVAS[1] - SPRITE_H - MARGIN_BOTTOM))

# 5. 量化到 256 索引色，关闭抖动
q = canvas.quantize(colors=256, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
out_main = OUT / "pc98_v3_tachie_white_640x400.png"
q.save(out_main)

# 6. 局部 3x 检查图（头部与胸襟）
zoom_box = (190, 10, 460, 250)
zoom = q.convert("RGB").crop(zoom_box).resize(
    ((zoom_box[2] - zoom_box[0]) * 3, (zoom_box[3] - zoom_box[1]) * 3), Image.NEAREST
)
out_zoom = OUT / "pc98_v3_zoom_3x.png"
zoom.save(out_zoom)

colors = q.getcolors(256)
print("mode:", q.mode, "size:", q.size, "colors:", len(colors) if colors else ">256")
print("dominant:", sorted(colors, reverse=True)[:8])
print("saved:", out_main)
print("saved:", out_zoom)
