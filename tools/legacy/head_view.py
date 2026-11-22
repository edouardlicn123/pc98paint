"""头部区域明度/色相网格：只看头顶到约 18% 身高，避免把腿当成脸。

用法：python tools/legacy/head_view.py 图.png [列数] [起始比例] [结束比例]
"""
import sys

import numpy as np
from PIL import Image

p = sys.argv[1]
W = int(sys.argv[2]) if len(sys.argv) > 2 else 40
r0 = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
r1 = float(sys.argv[4]) if len(sys.argv) > 4 else 0.18

im = Image.open(p).convert("RGB")
a = np.array(im).astype(float)
ink = (a < 240).any(axis=2)
rows = np.flatnonzero(ink.sum(axis=1) > 4)
cols = np.flatnonzero(ink.any(axis=0))
top, bot = rows[0], rows[-1]
left, right = cols[0], cols[-1]
h = bot - top + 1
y0 = top + int(h * r0)
y1 = top + int(h * r1)
crop = im.crop((left, y0, right + 1, y1))
H = max(6, int(W * crop.size[1] / max(crop.size[0], 1) * 0.5))
crop = crop.resize((W, H), Image.BOX)
c = np.array(crop).astype(float)
q = np.clip((c.mean(2) / 25.6).astype(int), 0, 9)
print(f"crop=({left},{y0})-({right},{y1}) grid={W}x{H}")
for row in q:
    print("".join(map(str, row)))
print("--hue--")
lum = c.mean(2)
sat = c.max(2) - c.min(2)
rr, gg, bb = c[..., 0], c[..., 1], c[..., 2]
hue = np.select(
    [(sat < 20) & (lum > 175), sat < 20, (rr >= gg) & (gg >= bb),
     (gg > rr) & (gg >= bb), (bb > rr) & (bb > gg)],
    ["W", ".", "R", "G", "B"], default="?")
for row in hue:
    print("".join(row))
