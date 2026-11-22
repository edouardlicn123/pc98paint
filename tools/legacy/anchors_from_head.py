"""从四栏设定图右侧的头部特写栏提取锚点，归一化到头部皮肤框。"""
import json
import sys
import numpy as np
from pathlib import Path
from PIL import Image


def main(src, dst):
    im = np.array(Image.open(src).convert("RGB"))
    W = im.shape[1]
    p = im[:, int(W * 0.76):]
    R, G, B = p[..., 0].astype(float), p[..., 1].astype(float), p[..., 2].astype(float)
    skin = (R > 120) & (R > G + 6) & (G > B - 12) & (R - B > 10)
    ys, xs = np.where(skin)
    if not len(ys):
        raise SystemExit("no skin in head panel")
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    lum = 0.299 * R + 0.587 * G + 0.114 * B
    band = (lum < 95)[y0:y1]
    eye_y = y0 + int(np.argmax(band.sum(1))) if band.size else y0 + (y1 - y0) // 2
    cx = int(np.median(xs))
    cand = skin.copy()
    cand[:eye_y + 2] = False
    cand[y1 - 3:] = False
    yy, xx = np.where(cand)
    if len(yy):
        i = int(np.argmin(np.abs(xx - cx) * 2 + (yy - eye_y) * 0.1))
        nx, ny = int(xx[i]), int(yy[i])
    else:
        nx, ny = cx, eye_y + (y1 - eye_y) // 2
    hh = max(y1 - y0, 1)
    anc = {"eye": round((eye_y - y0) / hh, 3), "chin": 1.0,
           "nose": [round((nx - x0) / max(x1 - x0, 1), 3), round((ny - y0) / hh, 3)]}
    Path(dst).write_text(json.dumps(anc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(anc, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
