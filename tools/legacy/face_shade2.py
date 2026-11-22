"""小脸立体感 v2：五条 1px 规则；锚点可来自检测(模式B)或头部特写(模式A)。"""
import json
import sys
import numpy as np
from pathlib import Path
from PIL import Image

SHADOW = (0.74, 18, -6, 14)
DEEP = (0.64, 26, -8, 22)
LIGHT_K = (1.10, 6, 4, 2)


def masks(img):
    a = img[..., :3].astype(float)
    op = img[..., 3] > 0
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    lum = 0.299 * R + 0.587 * G + 0.114 * B
    skin = (R > 120) & (R > G + 6) & (G > B - 12) & (R - B > 10) & op
    return a, op, lum, skin


def head_box(op):
    ys, xs = np.where(op)
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    h = y1 - y0 + 1
    return y0, y0 + int(h * 0.18), x0, x1, h


def detect_anchors(img):
    a, op, lum, skin = masks(img)
    y0, hy1, x0, x1, h = head_box(op)
    head = np.zeros_like(op)
    head[y0:hy1] = True
    hs = skin & head
    if hs.sum() < 30:
        return None
    hy, hx = np.where(hs)
    cx = int(np.median(hx))
    band = (lum < 95) & head
    b = band[y0:hy1]
    eye_y = y0 + int(np.argmax(b.sum(1))) if b.size else y0 + int((hy1 - y0) * 0.5)
    chin = hy1 - 1
    for y in range(hy1 - 1, y0, -1):
        if hs[y].sum() > 0.20 * (x1 - x0):
            chin = y
            break
    cand = hs.copy()
    cand[:eye_y + 2] = False
    cand[chin - 2:] = False
    yy, xx = np.where(cand)
    if len(yy):
        i = int(np.argmin(np.abs(xx - cx) * 2 + (yy - eye_y) * 0.1))
        nose = (int(xx[i]), int(yy[i]))
    else:
        nose = (cx, eye_y + (chin - eye_y) // 2)
    hh = max(chin - y0, 1)
    return {"eye": (eye_y - y0) / hh, "chin": 1.0,
            "nose": [(nose[0] - hx.min()) / max(hx.max() - hx.min(), 1),
                     (nose[1] - y0) / hh]}


def paint(img, anc):
    a, op, lum, skin = masks(img)
    y0, hy1, x0, x1, h = head_box(op)
    hs = skin.copy()
    hs[:y0] = False
    hs[hy1:] = False
    if hs.sum() < 30:
        return img, {"skip": "no skin"}
    hy, hx = np.where(hs)
    hx0, hx1 = int(hx.min()), int(hx.max())
    top = int(hy.min())
    fx = lambda f: int(hx0 + f * (hx1 - hx0))
    fy = lambda f: int(y0 + f * (hy1 - y0 - 1))
    eye_y = fy(anc["eye"])
    chin = fy(min(anc["chin"], 0.995))
    nose_x, nose_y = fx(anc["nose"][0]), fy(anc["nose"][1])
    cx = (hx0 + hx1) // 2

    out = img.copy()
    cnt = {"nose": 0, "socket": 0, "bang": 0, "neck": 0, "chin": 0}

    def near_skin(x, y, r=3):
        for d in range(r + 1):
            for dy in range(-d, d + 1):
                for dx in range(-d, d + 1):
                    yy, xx = y + dy, x + dx
                    if 0 <= yy < skin.shape[0] and 0 <= xx < skin.shape[1] and skin[yy, xx]:
                        return xx, yy
        return None

    def shade(x, y, spec):
        p = near_skin(x, y)
        if not p:
            return 0
        xx, yy = p
        k, dr, dg, db = spec
        r, g, b = out[yy, xx, :3].astype(float)
        out[yy, xx, :3] = [np.clip(r * k + dr, 0, 255), np.clip(g * k + dg, 0, 255),
                           np.clip(b * k + db, 0, 255)]
        return 1

    cnt["nose"] = shade(nose_x + 1, nose_y + 1, SHADOW)
    for dx in (-int(0.10 * (hx1 - hx0)), int(0.10 * (hx1 - hx0))):
        cnt["socket"] += shade(cx + dx, eye_y + 2, SHADOW)
    for x in range(hx0 + int(0.20 * (hx1 - hx0)), hx1 - int(0.20 * (hx1 - hx0)) + 1):
        cnt["bang"] += shade(x, top + 1, SHADOW)
    for y in range(chin + 1, min(chin + 4, out.shape[0])):
        for x in range(cx - max(2, int(0.06 * (hx1 - hx0))), cx + max(2, int(0.06 * (hx1 - hx0))) + 1):
            cnt["neck"] += shade(x, y, DEEP)
    p = near_skin(cx, chin - 2)
    if p:
        r, g, b = out[p[1], p[0], :3].astype(float)
        out[p[1], p[0], :3] = [np.clip(r * LIGHT_K[0] + LIGHT_K[1], 0, 255),
                               np.clip(g * LIGHT_K[0] + LIGHT_K[2], 0, 255),
                               np.clip(b * LIGHT_K[0] + LIGHT_K[3], 0, 255)]
        cnt["chin"] = 1
    return out, {"anchors": anc, "eye_y": int(eye_y), "chin": int(chin),
                 "nose": [int(nose_x), int(nose_y)], "painted": {k: int(v) for k, v in cnt.items()}}


if __name__ == "__main__":
    src, dst, rep = sys.argv[1], sys.argv[2], sys.argv[3]
    anc_path = sys.argv[4] if len(sys.argv) > 4 else None
    im = np.array(Image.open(src).convert("RGBA"))
    if anc_path:
        anc = json.loads(Path(anc_path).read_text(encoding="utf-8"))
    else:
        anc = detect_anchors(im)
        Path(dst.replace(".png", "_anchors.json")).write_text(
            json.dumps(anc, ensure_ascii=False, indent=2), encoding="utf-8")
    out, info = paint(im, anc)
    Image.fromarray(out, "RGBA").save(dst)
    Path(rep).write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(info, ensure_ascii=False))
