# -*- coding: utf-8 -*-
"""把 AI 生成的高分辨率原图处理成 PC-9801 风格素材：
640x400 / 单屏 16 色（12bit 调色板，每通道为 17 的倍数）/ Bayer 有序抖动 / 硬边立绘。
"""
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

SRC = os.path.dirname(os.path.abspath(__file__)) + "/pc98_src"
OUT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) + "/pc98"

BAYER8 = np.array([
    [0, 32, 8, 40, 2, 34, 10, 42],
    [48, 16, 56, 24, 50, 18, 58, 26],
    [12, 44, 4, 36, 14, 46, 6, 38],
    [60, 28, 52, 20, 62, 30, 54, 22],
    [3, 35, 11, 43, 1, 33, 9, 41],
    [51, 19, 59, 27, 49, 17, 57, 25],
    [15, 47, 7, 39, 13, 45, 5, 37],
    [63, 31, 55, 23, 61, 29, 53, 21],
], dtype=np.float64) / 64.0


def snap4bit(colors):
    """PC-98 的 4096 色 = RGB 各 4bit，即每个通道只能取 0,17,34,...,255"""
    return np.clip(np.round(np.array(colors, dtype=np.float64) / 17.0), 0, 15) * 17.0


# 针对「黄昏教室 + 水手服少女」这一场戏手工设计的 16 色盘：
# 黑/深靛 → 群青 → 灰蓝 → 紫 → 灰紫 → 淡紫 → 米白，
# 再加肤色 3 阶、夕照琥珀 2 阶、缎带红、黑板绿、木色。
SCENE_PALETTE = [
    (17, 17, 17),
    (34, 34, 68),
    (51, 68, 119),
    (85, 102, 153),
    (119, 102, 170),
    (170, 153, 187),
    (221, 204, 221),
    (255, 238, 221),
    (255, 204, 187),
    (238, 170, 153),
    (221, 136, 119),
    (255, 187, 119),
    (238, 136, 85),
    (221, 34, 68),
    (85, 119, 102),
    (187, 119, 102),
]


def make_palette(arrays, n=16):
    """用中位切分取候选色，再吸附到 12bit 网格并去重；
    另外固定预留黑/白/红/肤色四个功能色，模拟 PC-98 画师的调色板分工。"""
    fixed = [(17, 17, 17), (255, 238, 221), (221, 34, 51), (255, 204, 187)]
    rows = []
    for a in arrays:
        flat = a.reshape(-1, 3)
        step = max(1, flat.shape[0] // 60000)
        rows.append(flat[::step])
    data = np.concatenate(rows, axis=0)
    img = Image.fromarray(data.reshape(1, -1, 3).astype(np.uint8), "RGB")
    want = n - len(fixed) + 3
    q = img.quantize(colors=want, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    pal = np.array(q.getpalette()[: want * 3], dtype=np.float64).reshape(-1, 3)
    snapped = snap4bit(pal)

    colors = []
    for c in snapped:
        key = tuple(int(v) for v in c)
        if key not in colors:
            colors.append(key)
        if len(colors) >= n - len(fixed):
            break
    for a in fixed:
        if a not in colors:
            colors.append(a)
    while len(colors) < n:
        colors.append((17, 17, 34))
    return np.array(colors[:n], dtype=np.float64)


def dither_to_palette(rgb, palette, strength=62.0, alpha=None):
    h, w, _ = rgb.shape
    tile = np.tile(BAYER8, (h // 8 + 1, w // 8 + 1))[:h, :w]
    offset = (tile - 0.5) * strength
    arr = np.clip(rgb + offset[..., None], 0, 255)
    best = np.full((h, w), 1e18)
    idx = np.zeros((h, w), dtype=np.uint8)
    for i, c in enumerate(palette):
        d = ((arr - c) ** 2).sum(axis=2)
        m = d < best
        best[m] = d[m]
        idx[m] = i
    out = palette[idx].astype(np.uint8)
    if alpha is not None:
        out = np.concatenate([out, alpha[..., None]], axis=2)
    return out


def load_white_keyed(path):
    img = Image.open(path).convert("RGB")
    w, h = img.size
    for seed in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        ImageDraw.floodfill(img, seed, (255, 0, 255), thresh=26)
    arr = np.array(img)
    mask = (arr[:, :, 0] > 240) & (arr[:, :, 1] < 40) & (arr[:, :, 2] > 240)
    alpha = np.where(mask, 0, 255).astype(np.uint8)
    rgb = arr.copy()
    rgb[mask] = 255
    return rgb, alpha


def fit_sprite(rgb, alpha, box_w=256, box_h=290):
    ys, xs = np.where(alpha > 0)
    top, bottom, left, right = ys.min(), ys.max(), xs.min(), xs.max()
    crop_rgb = rgb[top:bottom + 1, left:right + 1]
    crop_a = alpha[top:bottom + 1, left:right + 1]
    ch, cw = crop_a.shape
    scale = min(box_w / cw, box_h / ch)
    nw, nh = max(1, int(round(cw * scale))), max(1, int(round(ch * scale)))
    im = Image.fromarray(crop_rgb).resize((nw, nh), Image.LANCZOS)
    am = Image.fromarray(crop_a).resize((nw, nh), Image.LANCZOS)
    canvas = np.zeros((box_h, box_w, 3), dtype=np.uint8)
    canvas[:] = 255
    ca = np.zeros((box_h, box_w), dtype=np.uint8)
    x0 = (box_w - nw) // 2
    y0 = box_h - nh
    canvas[y0:y0 + nh, x0:x0 + nw] = np.array(im)
    ca[y0:y0 + nh, x0:x0 + nw] = np.array(am)
    ca = np.where(ca > 128, 255, 0).astype(np.uint8)
    return canvas, ca


def add_crt(img, scale=2, scan=0.13):
    big = img.resize((img.width * scale, img.height * scale), Image.NEAREST).convert("RGB")
    a = np.array(big).astype(np.float64)
    # 淡扫描线
    a[1::2, :, :] *= (1.0 - scan)
    # 轻微辉光，模拟 CRT 的像素渗光
    glow = np.array(big.filter(ImageFilter.GaussianBlur(2.0))).astype(np.float64)
    a = np.clip(a * 0.9 + glow * 0.16, 0, 255)
    # 荧光屏暗角
    h, w, _ = a.shape
    yy, xx = np.mgrid[0:h, 0:w]
    d = (((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    a *= np.clip(1.06 - 0.16 * d, 0.82, 1.06)[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def draw_pixel_text(canvas, xy, text, font, fill):
    """先按 1bit 阈值渲染文字，得到硬边像素字，避免抗锯齿灰边。"""
    bbox = font.getbbox(text)
    w, h = bbox[2] + 6, bbox[3] + 6
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((3 - bbox[0], 3 - bbox[1]), text, font=font, fill=255)
    mask = mask.point(lambda v: 255 if v > 100 else 0)
    canvas.paste(Image.new("RGB", (w, h), fill), xy, mask)


def draw_ui(screen):
    d = ImageDraw.Draw(screen)
    x0, y0, x1, y1 = 14, 304, 626, 386
    d.rectangle([x0 - 3, y0 - 3, x1 + 3, y1 + 3], fill=(34, 34, 68))
    d.rectangle([x0 - 3, y0 - 3, x1 + 3, y1 + 3], outline=(255, 238, 221))
    d.rectangle([x0 - 1, y0 - 1, x1 + 1, y1 + 1], outline=(187, 119, 102))
    d.rectangle([x0, y0, x1, y1], fill=(17, 17, 17))
    d.rectangle([x0, y0 - 24, x0 + 78, y0 - 1], fill=(17, 17, 17), outline=(187, 119, 102))
    font = ImageFont.truetype("C:/Windows/Fonts/msgothic.ttc", 16)
    small = ImageFont.truetype("C:/Windows/Fonts/msgothic.ttc", 14)
    draw_pixel_text(screen, (x0 + 10, y0 - 22), "美咲", small, (255, 187, 119))
    lines = ["「……まだ、残ってたんだ」", "窓の外は、あの日と同じ夕焼けだった。"]
    for i, line in enumerate(lines):
        draw_pixel_text(screen, (x0 + 18, y0 + 14 + i * 26), line, font, (255, 238, 221))
    return screen


def grade(img, saturation=1.0, contrast=1.0):
    arr = np.array(img).astype(np.float64)
    gray = arr.mean(axis=2, keepdims=True)
    arr = gray + (arr - gray) * saturation
    arr = (arr - 128.0) * contrast + 128.0
    return np.clip(arr, 0, 255)


def main():
    os.makedirs(OUT, exist_ok=True)
    src_bg = os.path.join(SRC, "bg_classroom_src.jpg")
    src_ch = os.path.join(SRC, "tachie_girl_src.jpg")

    bg = Image.open(src_bg).convert("RGB").resize((640, 400), Image.LANCZOS)
    bg = grade(bg, saturation=1.14, contrast=1.08)
    rgb_ch, a_ch = load_white_keyed(src_ch)
    spr_rgb, spr_a = fit_sprite(rgb_ch, a_ch)
    spr_rgb = grade(Image.fromarray(spr_rgb), saturation=1.08, contrast=1.05)

    palette = np.array(SCENE_PALETTE, dtype=np.float64)
    if os.environ.get("AUTO_PALETTE"):
        palette = make_palette([bg.astype(np.uint8), spr_rgb[spr_a > 0].astype(np.uint8)], 16)
    print("palette:", [tuple(int(v) for v in c) for c in palette])

    bg_idx = dither_to_palette(np.array(bg), palette, strength=58)
    bg_img = Image.fromarray(bg_idx, "RGB")
    bg_img.save(os.path.join(OUT, "pc98_bg_classroom.png"))

    spr_idx = dither_to_palette(spr_rgb.astype(np.float64), palette, strength=44, alpha=spr_a)
    spr = Image.fromarray(spr_idx, "RGBA")
    spr.save(os.path.join(OUT, "pc98_tachie_girl.png"))

    # 合成 640x400 实际画面（同一块 16 色调色板）
    screen = bg_img.copy()
    screen.paste(spr, (376, 110), spr)
    screen = draw_ui(screen)
    screen.save(os.path.join(OUT, "pc98_screen_640x400.png"), optimize=True)
    add_crt(screen, scale=2).save(os.path.join(OUT, "pc98_screen_crt_2x.png"), optimize=True)
    add_crt(bg_img, scale=2).save(os.path.join(OUT, "pc98_bg_preview_2x.png"), optimize=True)

    # 立绘单独预览：放在棋盘格上，便于确认透明区域
    chk = Image.new("RGB", (256 * 2 + 32, 290 * 2 + 32), (60, 60, 60))
    d = ImageDraw.Draw(chk)
    for y in range(0, chk.height, 16):
        for x in range(0, chk.width, 16):
            if (x // 16 + y // 16) % 2 == 0:
                d.rectangle([x, y, x + 15, y + 15], fill=(96, 96, 110))
    big_spr = spr.resize((256 * 2, 290 * 2), Image.NEAREST)
    chk.paste(big_spr, (16, 16), big_spr)
    chk.save(os.path.join(OUT, "pc98_tachie_preview_2x.png"))

    print("done")


if __name__ == "__main__":
    main()
