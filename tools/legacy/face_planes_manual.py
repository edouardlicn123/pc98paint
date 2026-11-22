"""侧脸主体面：以侧脸暗面 + 刘海影 + 颈影 + 下巴亮构成体积（锚点为绝对像素）。"""
import json
import sys
import numpy as np
from pathlib import Path
from PIL import Image

SHADOW = (0.78, 14, -8, 16)
CORE = (0.70, 18, -9, 20)
DEEP = (0.62, 24, -10, 24)


def interp(y, pts):
    for i in range(len(pts) - 1):
        (y1, v1), (y2, v2) = pts[i], pts[i + 1]
        if y1 <= y <= y2:
            t = 0 if y2 == y1 else (y - y1) / (y2 - y1)
            return v1 + (v2 - v1) * t
    return pts[-1][1]


def main(src, dst, rep, ex, ey, nx, ny, cx_, cy):
    img = np.array(Image.open(src).convert("RGBA"))
    a = img[..., :3].astype(float)
    op = img[..., 3] > 0
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    skin = (R > 120) & (R > G + 6) & (G > B - 12) & (R - B > 10) & op
    hs = skin.copy()
    hs[int(cy) + 6:] = False
    ys, xs = np.where(hs)
    top = int(ys.min())
    ws = []
    for y in range(top, int(cy) + 1):
        xs_row = np.where(skin[y])[0]
        if xs_row.size:
            ws.append(int(xs_row.max() - xs_row.min()))
    w = max(ws) if ws else 1
    out = img.copy()

    # 颈部本身已偏暗，放宽阈值专门用于颈影；排蓝黑发与白领
    neck_mask = op & (R > 92) & (R > G + 3) & (R - B > 4)

    def put(x, y, spec, mask=skin):
        if 0 <= y < mask.shape[0] and 0 <= x < mask.shape[1] and mask[y, x]:
            k, dr, dg, db = spec
            r, g, b = out[y, x, :3].astype(float)
            out[y, x, :3] = [np.clip(r * k + dr, 0, 255), np.clip(g * k + dg, 0, 255),
                             np.clip(b * k + db, 0, 255)]
            return 1
        return 0

    pts = [(top, 0.04), (ey, 0.12), (ny, 0.10), (cy, 0.04)]
    n_side = n_core = n_bang = n_neck = n_chin = 0
    for y in range(top, top + 4):
        for x in range(cx_ - int(0.35 * w), cx_ + int(0.35 * w) + 1):
            n_bang += put(x, y, SHADOW)
    for y in range(top, cy + 1):
        xs_row = np.where(skin[y])[0]
        if xs_row.size:
            for x in (int(xs_row.min()), int(xs_row.max())):
                n_side += put(x, y, SHADOW)
    for y in (cy - 1, cy):
        for x in range(cx_ - int(0.10 * w), cx_ + int(0.10 * w) + 1):
            n_side += put(x, y, CORE)
    for y in range(ey, ny + 1):
        for x in range(cx_ + 1, cx_ + max(2, int(0.04 * w)) + 1):
            n_core += put(x, y, CORE)
    for y in range(cy + 1, cy + 9):
        for x in range(cx_ - int(0.12 * w), cx_ + int(0.12 * w) + 1):
            n_neck += put(x, y, DEEP, neck_mask)
    for x in range(cx_ - int(0.06 * w), cx_ + int(0.06 * w) + 1):
        y = cy - 2
        if 0 <= y < skin.shape[0] and skin[y, x]:
            r, g, b = out[y, x, :3].astype(float)
            out[y, x, :3] = [np.clip(r * 1.12 + 8, 0, 255), np.clip(g * 1.07 + 5, 0, 255),
                             np.clip(b * 1.03 + 3, 0, 255)]
            n_chin += 1

    Image.fromarray(out, "RGBA").save(dst)
    info = {"face_width": w, "top": top, "painted": {"side": int(n_side), "nose_core": int(n_core),
            "bang": int(n_bang), "neck": int(n_neck), "chin": int(n_chin)}}
    Path(rep).write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(info, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], *map(int, sys.argv[4:10]))
