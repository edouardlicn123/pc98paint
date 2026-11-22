"""生成带坐标网格的头部放大图（含左侧/顶部坐标栏），用于人工标点。"""
import sys
import numpy as np
from PIL import Image, ImageDraw

src, dst = sys.argv[1], sys.argv[2]
im = Image.open(src).convert("RGBA")
a = np.array(im)
op = a[..., 3] > 0
ys, xs = np.where(op)
y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
h = y1 - y0 + 1
hy1 = y0 + int(h * 0.30)
S = 4
MX, MY = 46, 22
cw, ch = (x1 - x0 + 1) * S, (hy1 - y0) * S
crop = im.crop((x0, y0, x1 + 1, hy1)).resize((cw, ch), Image.NEAREST)
canvas = Image.new("RGB", (cw + MX, ch + MY), (255, 255, 255))
canvas.paste(crop, (MX, MY))
d = ImageDraw.Draw(canvas)
for gx in range(0, x1 - x0 + 1, 10):
    c = (255, 0, 0) if gx % 50 == 0 else (120, 200, 120)
    d.line([(MX + gx * S, MY), (MX + gx * S, MY + ch)], fill=c, width=1)
    if gx % 20 == 0:
        d.text((MX + gx * S + 1, 5), str(int(x0 + gx)), fill=(0, 0, 0))
for gy in range(0, hy1 - y0 + 1, 10):
    c = (255, 0, 0) if gy % 50 == 0 else (120, 200, 120)
    d.line([(MX, MY + gy * S), (MX + cw, MY + gy * S)], fill=c, width=1)
    if gy % 20 == 0:
        d.text((3, MY + gy * S - 4), str(int(y0 + gy)), fill=(0, 0, 0))
canvas.save(dst)
print({"crop": [int(x0), int(y0), int(x1) + 1, int(hy1)], "scale": S, "size": canvas.size})
