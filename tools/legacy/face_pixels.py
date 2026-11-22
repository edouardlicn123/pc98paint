"""小脸立体感：锚定五官像素，只加 1px 面。不做几何猜测。"""
import json
import sys
import numpy as np
from pathlib import Path
from PIL import Image

SHADOW = (0.74, 18, -6, 14)   # 乘 0.74，向玫红/紫偏移
DEEP = (0.66, 26, -8, 20)


def paint(img):
    a = img[..., :3].astype(float)
    al = img[..., 3]
    op = al > 0
    ys, xs = np.where(op)
    if not len(ys):
        return img, {}
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    h, w = y1 - y0 + 1, x1 - x0 + 1
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    lum = 0.299 * R + 0.587 * G + 0.114 * B
    skin = (R > 120) & (R > G + 6) & (G > B - 12) & (R - B > 10) & op
    head = np.zeros_like(op)
    head[y0:y0 + int(h * 0.18)] = True
    hs = skin & head
    if hs.sum() < 40:
        return img, {"skip": "no head skin"}

    hy, hx = np.where(hs)
    cx = int(np.median(hx))

    # 眼线：头部上 10% 内暗像素最多的行
    dark = (lum < 95) & head
    band = dark[y0:y0 + int(h * 0.10)]
    eye_y = y0 + int(np.argmax(band.sum(1))) if band.size else y0 + int(h * 0.09)

    # 鼻点：眼线下方、靠近中线的最暗像素
    cand = hs.copy()
    cand[:eye_y + 2] = False
    yy, xx = np.where(cand)
    if len(yy):
        i = int(np.argmin(np.abs(xx - cx) * 2 + (yy - eye_y) * 0.2))
        nose_y, nose_x = int(yy[i]), int(xx[i])
    else:
        nose_y, nose_x = eye_y + 3, cx

    # 下巴：皮肤行宽仍 > 0.22 头宽的最底行
    chin = y0 + int(h * 0.14)
    for y in range(y0 + int(h * 0.17), y0, -1):
        if hs[y].sum() > 0.22 * w:
            chin = y
            break

    out = img.copy()
    painted = {"nose": 0, "socket": 0, "bang": 0, "neck": 0, "chin": 0}

    def put(x, y, spec=SHADOW):
        k, dr, dg, db = spec
        if 0 <= y < out.shape[0] and 0 <= x < out.shape[1] and skin[y, x]:
            r, g, b = out[y, x, :3].astype(float)
            out[y, x, 0] = np.clip(r * k + dr, 0, 255)
            out[y, x, 1] = np.clip(g * k + dg, 0, 255)
            out[y, x, 2] = np.clip(b * k + db, 0, 255)
            return 1
        return 0

    def light(x, y):
        if 0 <= y < out.shape[0] and skin[y, x]:
            r, g, b = out[y, x, :3].astype(float)
            out[y, x, 0] = np.clip(r * 1.10 + 6, 0, 255)
            out[y, x, 1] = np.clip(g * 1.06 + 4, 0, 255)
            out[y, x, 2] = np.clip(b * 1.02 + 2, 0, 255)
            return 1
        return 0

    # 1 鼻侧 1px（紧贴鼻点右下）
    painted["nose"] = put(nose_x + 1, nose_y + 1)
    # 2 眼窝 1px（眼下各一个）
    for dx in (-int(0.10 * w), int(0.10 * w)):
        painted["socket"] += put(cx + dx, eye_y + 2)
    # 3 刘海投影 1px（最上皮肤行下方）
    top = int(np.where(hs.any(1))[0].min())
    for x in range(x0 + int(0.28 * w), x1 - int(0.28 * w) + 1):
        painted["bang"] += put(x, top + 1)
    # 4 下颌/颈 1px（下巴下方三行，窄区域，更深）
    for y in range(chin + 1, min(chin + 4, out.shape[0])):
        for x in range(cx - int(0.07 * w), cx + int(0.07 * w) + 1):
            painted["neck"] += put(x, y, DEEP)
    # 5 下巴 1px 亮
    painted["chin"] = light(cx, chin - 1)

    return out, {
        "eye_y": int(eye_y), "chin": int(chin), "nose": [int(nose_x), int(nose_y)],
        "painted": {k: int(v) for k, v in painted.items()},
        "nose_hue_ok": bool((out[nose_y + 1, nose_x + 1, 0].astype(float)
                             - out[nose_y + 1, nose_x + 1, 2]) > 8),
        "jaw_sep": float(lum[chin - 1, cx] - lum[min(chin + 2, out.shape[0] - 1), cx]),
    }


if __name__ == "__main__":
    src, dst, rep = sys.argv[1], sys.argv[2], sys.argv[3]
    im = Image.open(src).convert("RGBA")
    arr, info = paint(np.array(im))
    Image.fromarray(arr, "RGBA").save(dst)
    Path(rep).write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(info, ensure_ascii=False))
