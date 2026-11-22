"""人工锚点版：五条 1px 规则，坐标为立绘绝对像素。"""
import json
import sys
import numpy as np
from pathlib import Path
from PIL import Image

SHADOW = (0.74, 18, -6, 14)
DEEP = (0.64, 26, -8, 22)


def main(src, dst, rep, ex, ey, nx, ny, cx_, cy):
    img = np.array(Image.open(src).convert("RGBA"))
    a = img[..., :3].astype(float)
    op = img[..., 3] > 0
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    skin = (R > 120) & (R > G + 6) & (G > B - 12) & (R - B > 10) & op
    out = img.copy()
    cnt = {"nose": 0, "socket": 0, "bang": 0, "neck": 0, "chin": 0}

    def near(x, y, r=3):
        for d in range(r + 1):
            for dy in range(-d, d + 1):
                for dx in range(-d, d + 1):
                    yy, xx = y + dy, x + dx
                    if 0 <= yy < skin.shape[0] and 0 <= xx < skin.shape[1] and skin[yy, xx]:
                        return xx, yy
        return None

    def shade(x, y, spec):
        p = near(x, y)
        if not p:
            return 0
        xx, yy = p
        k, dr, dg, db = spec
        r, g, b = out[yy, xx, :3].astype(float)
        out[yy, xx, :3] = [np.clip(r * k + dr, 0, 255), np.clip(g * k + dg, 0, 255),
                           np.clip(b * k + db, 0, 255)]
        return 1

    cnt["nose"] = shade(nx + 1, ny + 1, SHADOW)
    for dx in (-16, 16):
        cnt["socket"] += shade(ex + dx, ey + 2, SHADOW)
    ys, xs = np.where(skin)
    top = int(ys.min())
    for x in range(ex - 45, ex + 46):
        cnt["bang"] += shade(x, top + 1, SHADOW)
    for y in range(cy + 1, cy + 4):
        for x in range(cx_ - 9, cx_ + 10):
            cnt["neck"] += shade(x, y, DEEP)
    p = near(cx_, cy - 2)
    if p:
        r, g, b = out[p[1], p[0], :3].astype(float)
        out[p[1], p[0], :3] = [np.clip(r * 1.10 + 6, 0, 255),
                               np.clip(g * 1.06 + 4, 0, 255), np.clip(b * 1.02 + 2, 0, 255)]
        cnt["chin"] = 1

    Image.fromarray(out, "RGBA").save(dst)
    info = {"anchors": {"eye": [ex, ey], "nose": [nx, ny], "chin": [cx_, cy]},
            "painted": {k: int(v) for k, v in cnt.items()}}
    Path(rep).write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(info, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], *map(int, sys.argv[4:10]))
