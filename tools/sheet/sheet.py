# -*- coding: utf-8 -*-
"""三视图：生成提示、面部结构校验、立绘面部结构继承。

用法：
    python tools/sheet/sheet.py --prompt characters/akira/spec.json
    python tools/sheet/sheet.py --from-sheet _work/pc98_src/akira_sheet.jpg \
        --spec characters/akira/spec.json --out pc98/akira_v2
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation, label

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "output"          # 产出统一写 output/（见 AGENTS.md）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
sys.path.insert(0, str(ROOT / "tools" / "lib"))

import pixelize  # noqa: E402
import repair  # noqa: E402
import schema  # noqa: E402

SHEET_POS = (
    "character design sheet, three FULL-LENGTH full body views side by side: front view, side view, back view, "
    "ENTIRE body visible from head to shoes, whole legs, feet and shoes included, no cropping at waist or knees, "
    "generous white margin above the head and below the feet, feet on the same baseline, "
    "same character, same costume, same palette, neutral standing pose, arms slightly away from body, "
    "solid white background, no perspective, "
    "one key light from the upper left in all views: the lit side is on the image-left of the face, "
    "1990s PC-98 galgame style, cel-shaded, hard-edged flat shading, 3-4 tones per material, "
    "face shadow design: the face is completely flat, one single bright skin tone, no cast shadow on the face, "
    "no blush, no pink cheek circles; "
    "bangs cast a 1px shadow on the forehead; jaw line 1px; neck one tone darker than the face; one small nose-side shadow; "
    "blocky hair masses; cream hair highlight: exactly 2-3 LARGE hard-edged elongated blocks in total, following the hair flow across the crown and bangs, "
    "tapered at both ends, no scattered round highlight dots, no polka-dot sheen; "
    "simplified nose and mouth, 1px dark line art"
)
SHEET_NEG = (
    "half body, waist-up, knee-up, cropped legs, missing feet, cut off at bottom, "
    "modern anime, 8-head proportions, detailed hair strands, soft shading, gradients, glossy, "
    "broad half-face shadow, large dark side plane, heavy facial shadow covering half the face, dirty face shading, "
    "shadow on both cheeks, ambient occlusion on the face, isolated oval shadow patch on the cheek, "
    "pink blush circles, round blush spots on the cheeks, red cheeks, blush hatch lines, blush texture, "
    "scattered round hair highlights, polka dot hair sheen, many small cream spots, "
    "painterly, blurry, text, watermark, multiple characters overlapping"
)


def prompt_for(spec):
    h, o = spec["hair"], spec["outfit"]
    return (
        f"{SHEET_POS}, {spec['proportions']['heads']} head proportions, "
        f"{h['length']} {h['color']} hair, {h['bangs_blocks']} bang blocks, "
        f"{o['type']} uniform, {o['base']} base, {o['collar']} collar, {o['accent']} accent",
        SHEET_NEG,
    )


def split_views(path):
    """按最大连通块切出三视图（标题文字/基准线不算），返回 [前, 侧, 后]。"""
    im = Image.open(path).convert("RGB")
    a = np.array(im)
    pad = 6  # 裁掉四周的边框线
    a = a[pad:-pad, pad:-pad]
    # 基准不一定是连续实线：3072px 的设定稿上一条断断续续的脚线只覆盖
    # 85% 宽度，按 98% 判断会漏掉，并排的三视图就被连成一块（2026-11-22）。
    # 单个人物行覆盖率不超过 0.5，用 0.6 作为"横贯线"阈值。
    ink = (a < 240).any(axis=2)
    a[ink.mean(axis=1) > 0.6] = 255  # 横贯全图的基准线
    ink = (a < 240).any(axis=2)
    # 基准线的抗锯齿残行会把并排的人连成一块，上下各清 2 行
    a[binary_dilation(ink.mean(axis=1) > 0.6, np.ones(5))] = 255
    ink = (a < 240).any(axis=2)
    lab, n = label(ink)
    total = ink.sum()
    boxes = []
    for i in range(1, n + 1):
        ys, xs = np.where(lab == i)
        if xs.size < total * 0.03:  # 标题文字、噪点
            continue
        boxes.append((xs.min(), xs.max(), ys.min(), ys.max()))
    boxes = sorted(boxes, key=lambda b: -(b[1] - b[0]) * (b[3] - b[2]))[:3]
    boxes.sort(key=lambda b: b[0])
    return [im.crop((x0 + pad, y0 + pad, x1 + 1 + pad, y1 + 1 + pad))
            for x0, x1, y0, y1 in boxes]


def sheet_lint(path, spec):
    im = Image.open(path).convert("RGB")
    a = np.array(im).astype(np.int16)
    ink = (a < 240).any(axis=2)
    rows = np.flatnonzero(ink.sum(axis=1) > 6)
    cols = np.flatnonzero(ink.any(axis=0))
    bh, bw = rows[-1] - rows[0] + 1, cols[-1] - cols[0] + 1
    aspect = bh / max(bw, 1)

    bottom = ink[int(rows[0] + bh * 0.94):rows[-1] + 1]
    feet_dark = float(((a < 120).any(axis=2)[int(rows[0] + bh * 0.94):rows[-1] + 1]).mean()) if bottom.size else 0.0
    margin_top = float(rows[0] / a.shape[0])
    margin_bottom = float((a.shape[0] - 1 - rows[-1]) / a.shape[0])

    # 面部指标只取头部区域（头顶起 18% 身高），避免把躯干/腿的皮肤算进来
    head = np.zeros_like(ink)
    head[rows[0]:rows[0] + int(bh * 0.18)] = True
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    # 奶油色高光/白领的 R-G 很小，用 R-G 把非肤色排除；阴影偏灰紫但 R-G 仍大，会保留
    skin = (R > 110) & ((R - G) > 12) & ((R - B) > 8)
    # 沿发丝的抗锯齿暖色碎点会把脸的外接框撑大，只取最大且紧凑的连通块当脸
    lab0, n0 = label(skin & head)
    face = skin & head
    for i in np.argsort(-np.bincount(lab0.ravel())[1:])[:8] + 1:
        ys, xs = np.where(lab0 == i)
        w_, h_ = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
        if 0.5 < w_ / h_ < 1.8 and xs.size / (w_ * h_) > 0.35:
            face = lab0 == i
            break
    if face.sum() < 500:
        return {"pass": False, "reason": "未检测到皮肤区域"}
    px = a[face]
    # 量化后取覆盖 90% 面积的主色数（3bit/通道），抗锯齿过渡色不会算成独立色阶
    q = (px // 32) * 32
    cols_u, counts = np.unique(q, axis=0, return_counts=True)
    share = counts / counts.sum()
    tones = int(np.searchsorted(np.cumsum(np.sort(share)[::-1]), 0.9) + 1)
    lum = 0.299 * px[:, 0] + 0.587 * px[:, 1] + 0.114 * px[:, 2]
    dark_share = float((lum < np.median(lum) - 25).mean())
    checks = {
        "full_body": {"value": round(aspect, 2), "limit": ">=2.0", "pass": bool(aspect >= 2.0)},
        "feet_visible": {"value": round(feet_dark, 3), "limit": ">=0.02", "pass": bool(feet_dark >= 0.02)},
        "face_tones": {"value": tones, "limit": [2, 9], "pass": bool(2 <= tones <= 9)},
        "shadow_share": {"value": round(dark_share, 3), "limit": [0.05, 0.45],
                         "pass": bool(0.05 <= dark_share <= 0.45)},
    }
    # 面部阴影应窄、单侧、落在受光反侧（图右），且必须焊在轮廓上（孤立色斑=错）
    fy, fx = np.where(face)
    if len(fy) > 50:
        rel = lum < np.median(lum) - 20
        h = max(fy.max() - fy.min(), 1)
        low = fy >= fy.min() + 0.5 * h
        x0, x1 = fx[low].min(), fx[low].max()
        band = max(int((x1 - x0) * 0.22), 1)
        left, right = low & (fx < x0 + band), low & (fx > x1 - band)
        l = float(rel[left].mean()) if left.any() else 0.0
        r = float(rel[right].mean()) if right.any() else 0.0
        mid = (fy > fy.min() + 0.30 * h) & (fy < fy.min() + 0.78 * h) & (fx > x1 - band)
        dr = mid & rel
        touch = bool(dr.any() and fx[dr].max() >= x1 - max(int(0.02 * (x1 - x0)), 2))
        span = float(fy[dr].max() - fy[dr].min()) / h if dr.any() else 0.0
        # 带宽逐行测量取中位数。两个口径修正（2026-11-21）：
        # 1) 只统计"暖色暗像素"（R-G 仍大）：玫瑰紫暗带保持暖色相，
        #    而贴发际线/轮廓的抗锯齿混色像素是冷灰的，会被排除；
        # 2) 逐行取右缘起连续段再取中位数：跨行 max-min 会把下颌
        #    轮廓的横向内收累加进带宽（假阳性）。
        warm_min = max(25.0, 0.45 * float(np.median(px[:, 0] - px[:, 1])))
        relw = rel & ((px[:, 0] - px[:, 1]) > warm_min)
        dr = mid & relw
        if not dr.any():
            dr = mid & rel   # 兜底：无暖暗像素时退回普通暗像素口径
        row_sets = {}
        for yy_, xx_ in zip(fy[dr], fx[dr]):
            row_sets.setdefault(int(yy_), set()).add(int(xx_))
        rw = []
        for s in row_sets.values():
            x = max(s)
            wcnt, gap = 1, 0
            while x - 1 >= x0 and gap <= 1:
                x -= 1
                if x in s:
                    wcnt += 1
                    gap = 0
                else:
                    gap += 1
            rw.append(wcnt)
        width = float(np.median(rw)) / max(x1 - x0, 1) if rw else 1.0
        hi, lo = max(l, r), min(l, r)
        checks["shadow_band"] = {"value": [round(l, 2), round(r, 2), round(width, 2)],
                                 "limit": "right>left, touch contour, width<=0.18",
                                 "pass": bool(r > l and hi >= 0.08 and hi >= 1.4 * lo and touch and width <= 0.18)}
    # 头发高光应为少数长条块，而不是散落圆斑：先合并被发丝切开的高光块再数
    fg = (a < 250).any(axis=2)
    cream = (fg & head & (R > 215) & (G > 210) & (B > 218)
             & ((R - G) < 20) & ((G - B) < 18) & (np.minimum(np.minimum(R, G), B) < 250))
    lab2, _ = label(binary_dilation(cream, np.ones((9, 9))))
    sizes = np.bincount(lab2.ravel())[1:]
    sizes = sizes[sizes >= 40]
    if sizes.size:
        share_big = float(sizes.max() / sizes.sum())
        checks["hair_highlight"] = {"value": [int(sizes.size), round(share_big, 2)],
                                    "limit": "blocks<=12, largest>=0.30",
                                    "pass": bool(sizes.size <= 12 and share_big >= 0.30)}
    return {"pass": all(v["pass"] for v in checks.values()), "checks": checks}


def face_fix(img):
    """面部归整：清掉脸上的软阴影/腮红圆斑，再在受光反侧轮廓画窄暗带。

    生成模型给不出稳定的"窄单侧影"，这一步把它变成确定性的像素规则：
    - 脸内只剩一个亮面：软阴影（中等变暗）全脸清掉，很深的五官色
      （嘴线、睫毛）不在清理窗口内，不受影响；
    - 暗带焊在可见轮廓上：从皮肤掩码右缘向右越过相邻的描线/抗锯齿
      像素（≤5px，遇白背景即停）——否则带与轮廓之间会留亮缝，
      立绘缩小后读作"描线发虚"（2026-11-21 试错）；
    - 宽度沿下颌方向单调渐宽（约 5%→11% 脸宽），纵向渐入渐出，
      不做周期交替（交替会产生齿轮状锯齿）。
    """
    a = np.array(img.convert("RGB")).astype(np.int16)
    h = a.shape[0]
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    bg_white = a.min(axis=2) >= 245
    skin = (R > 110) & ((R - G) > 12) & ((R - B) > 8)
    zone = np.zeros_like(skin)
    zone[:int(h * 0.25)] = True
    lab, n = label(skin & zone)
    if n == 0:
        return img
    face = None
    for i in np.argsort(-np.bincount(lab.ravel())[1:])[:8] + 1:
        ys, xs = np.where(lab == i)
        w_, h_ = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
        if 0.5 < w_ / h_ < 1.8 and xs.size / (w_ * h_) > 0.35:
            face = lab == i
            break
    if face is None:
        return img
    fy, fx = np.where(face)
    y0, y1 = int(fy.min()), int(fy.max())
    fh, fw = max(y1 - y0, 1), max(int(fx.max() - fx.min()), 1)
    px = a[face]
    base = np.percentile(px, 70, axis=0)
    base_lum = 0.299 * base[0] + 0.587 * base[1] + 0.114 * base[2]
    lum = 0.299 * R + 0.587 * G + 0.114 * B
    out = a.copy()
    # 1) 全脸清软阴影：中等变暗的斑块压回亮面基色；窗口外保留深五官色
    dirty = face & (lum < base_lum - 15) & (lum > base_lum - 60)
    out[dirty] = base.astype(np.int16)
    # 2) 右轮廓窄暗带：玫瑰紫偏色，焊在可见轮廓上，纵向渐入渐出
    tone = np.array([base[0] * 0.86, base[1] * 0.70, base[2] * 0.74])
    band_y0, band_y1 = y0 + int(fh * 0.45), y0 + int(fh * 0.95)
    span = max(band_y1 - band_y0, 1)
    for y in range(band_y0, band_y1 + 1):
        xs = np.where(face[y])[0]
        if not xs.size:
            continue
        x1 = int(xs.max())
        # 越过相邻描线/抗锯齿像素焊到可见轮廓（遇白背景即停）
        xe = x1
        for k in range(1, 6):
            if x1 + k >= a.shape[1] or bg_white[y, x1 + k]:
                break
            xe = x1 + k
        t = (y - band_y0) / span                       # 0→1 沿下颌方向
        fade = min(t / 0.18, 1.0) * min((1 - t) / 0.12, 1.0)
        fade = max(fade, 0.0)
        bw = int(round(fw * (0.05 + 0.06 * t) * (0.4 + 0.6 * fade)))
        bw = max(1, bw)
        out[y, max(xe - bw + 1, 0):xe + 1] = tone
    return Image.fromarray(out.astype(np.uint8), "RGB")


def cloth_fix(img):
    """下身白色织物（袜子）阴影归整：软渐变阴影压成单一硬边平涂色。

    生成模型在白袜上画的是软渐变的灰蓝阴影，经像素化量化后成为
    不规则的灰蓝污渍，阴影内的白色褶皱线变成锯齿波浪（2026-11-21
    用户反馈"油污色"）。PC-98 赛璐璐规范下白色织物只有两个色阶：
    奶白基色 + 单一冷灰阴影，这里按亮度阈值把织物区二值归色，
    深于阈值的描线与鞋子不受影响。只处理下半身（y>0.75）的大块
    近白连通块，领口/袖口不受影响。
    """
    a = np.array(img.convert("RGB")).astype(np.int16)
    h = a.shape[0]
    lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    near_white = (a.min(axis=2) > 170) & (np.ptp(a, axis=2) < 45)
    zone_y = np.zeros_like(near_white)
    zone_y[int(h * 0.75):] = True
    lab, n = label(near_white & zone_y)
    out = a.copy()
    touched = False
    for i in range(1, n + 1):
        m = lab == i
        if m.sum() < 800:
            continue
        # 织物区：连通块外扩 2px，容纳贴边的阴影与抗锯齿像素
        zone = binary_dilation(m, np.ones((5, 5)))
        base = np.percentile(a[m], 75, axis=0)
        # 基色封顶为暖奶油白：一是 PC-98 规范"纯白只留给高光锚点"，
        # 二是织物若含 ≥245 的近纯白像素，会在像素化的背景检测中
        # 与白色背景连通而被判成背景 → 袜子上出现透明洞（2026-11-21）
        base = np.minimum(base, np.array([244.0, 239.0, 228.0]))
        base_lum = 0.299 * base[0] + 0.587 * base[1] + 0.114 * base[2]
        t_white = base_lum - 14          # 白/阴影像素分界
        t_line = base_lum - 55           # 深于此为描线，不动
        fab = zone & (lum > t_line)
        shadow = fab & (lum <= t_white)
        white = fab & (lum > t_white)
        # 平涂阴影色：取源图阴影的中位色相；样本不足则回退到冷色偏移
        sh = a[shadow & near_white]
        tone = (np.percentile(sh, 40, axis=0) if sh.shape[0] >= 40
                else base * np.array([0.84, 0.85, 0.92]))
        out[white] = base.astype(np.int16)
        out[shadow] = tone.astype(np.int16)
        touched = True
    if not touched:
        return img
    return Image.fromarray(out.astype(np.uint8), "RGB")


def face_boost(img, k=5):
    a = np.array(img)
    rgb, fg = a[..., :3].astype(np.int16), a[..., 3] > 0
    h = a.shape[0]
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    yy = np.mgrid[0:h, 0:a.shape[1]][0]
    skin = fg & (yy < int(h * 0.32)) & (R > 150) & (R >= G) & ((R - B) > 14) & ((R - B) < 90)
    if skin.sum() > 200:
        rgb[skin] = repair._kmeans(rgb[skin].astype(np.uint8), k=k)
    return Image.fromarray(np.dstack([rgb.astype(np.uint8), a[..., 3]]), "RGBA")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt")
    ap.add_argument("--from-sheet")
    ap.add_argument("--front")
    ap.add_argument("--spec", default="characters/akira/spec.json")
    ap.add_argument("--out", default="akira_v2")   # 产出落在 output/ 下
    args = ap.parse_args()
    spec = schema.load(ROOT / args.spec)

    if args.prompt:
        pos, neg = prompt_for(spec)
        print("PROMPT:", pos)
        print("NEGATIVE:", neg)
        return

    if args.front:
        front = Image.open(ROOT / args.front).convert("RGB")
        views = [front]
    else:
        views = split_views(ROOT / args.from_sheet)
    if len(views) < 1:
        raise SystemExit("未能切出三视图")
    front = views[0]
    front_path = ROOT / "_work" / "pc98_src" / "akira_front.png"
    face_fix(cloth_fix(front)).save(front_path)
    print("views", len(views), "front", front.size)

    out_prefix = OUT_DIR / Path(args.out).name   # 一律落到 output/ 下
    img, stats = pixelize.pixelize(front_path, spec["render"], out_prefix)
    img = face_boost(img)
    img = repair.palette_lock(img, spec)
    img = repair.eyebrow_fix(img, spec)
    img = repair.drop_specks(img)
    img.save(str(out_prefix) + "_tachie.png")
    report = {"sprite": stats, "sheet": sheet_lint(front_path, spec)}
    (Path(str(out_prefix) + "_report.json")).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

