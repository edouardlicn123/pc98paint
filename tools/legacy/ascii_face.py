"""定位最大紧凑肤色块（脸），输出其明度/色相网格。"""
import sys
import numpy as np
from PIL import Image
from scipy import ndimage

p = sys.argv[1]
im = Image.open(p).convert("RGB")
a = np.array(im).astype(float)
R, G, B = a[..., 0], a[..., 1], a[..., 2]
skin = (R > 105) & (R > G + 6) & (R - B > 10)
skin = ndimage.binary_closing(skin, np.ones((3, 3)))
lab, n = ndimage.label(skin)
best = None
for i in range(1, n + 1):
    ys, xs = np.where(lab == i)
    if xs.size < 300:
        continue
    w = xs.max() - xs.min() + 1
    h = ys.max() - ys.min() + 1
    ar = w / h
    fill = xs.size / (w * h)
    score = xs.size * fill * (1 if 0.55 < ar < 1.6 else 0.3)
    if best is None or score > best[0]:
        best = (score, xs.min(), ys.min(), xs.max(), ys.max())
if not best:
    print("no face"); sys.exit(1)
_, x0, y0, x1, y1 = best
pad_x = int((x1 - x0) * 0.12); pad_y = int((y1 - y0) * 0.12)
x0, y0 = max(0, x0 - pad_x), max(0, y0 - pad_y)
x1, y1 = min(a.shape[1], x1 + pad_x), min(a.shape[0], y1 + pad_y)
crop = im.crop((x0, y0, x1, y1))
W = 34
H = max(8, int(W * (y1 - y0) / max(x1 - x0, 1) * 0.55))
crop = crop.resize((W, H), Image.BOX)
c = np.array(crop).astype(float)
q = np.clip((c.mean(2) / 25.6).astype(int), 0, 9)
print(f"face bbox=({x0},{y0})-({x1},{y1}) grid={W}x{H}")
for row in q:
    print("".join(map(str, row)))
print("--hue--")
lum = c.mean(2); sat = c.max(2) - c.min(2)
rr, gg, bb = c[..., 0], c[..., 1], c[..., 2]
hue = np.select([(sat < 20) & (lum > 175), sat < 20, (rr >= gg) & (gg >= bb), (gg > rr) & (gg >= bb), (bb > rr) & (bb > gg)],
                ["W", ".", "R", "G", "B"], default="?")
for row in hue:
    print("".join(row))
