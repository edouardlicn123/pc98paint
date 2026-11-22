# -*- coding: utf-8 -*-
"""特写 / 半身 / 全身三种构图，统一按 640×400 参考规则输出。"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
from scipy.ndimage import binary_dilation, label

ROOT = Path(__file__).resolve().parents[2]
LIB = Path(__file__).resolve().parents[1] / "lib"
COMMON = Path(__file__).resolve().parents[1] / "common"
SRC = ROOT / "_work" / "pc98_src"
sys.path.insert(0, str(LIB))
sys.path.insert(0, str(COMMON))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pc98_sprite_v7 as v7  # noqa: E402
import bust_sample2 as bs  # noqa: E402
import palette98 as p98  # noqa: E402
import lint  # noqa: E402
import matregion  # noqa: E402
import drawing  # noqa: E402

W, H = 640, 400
MARGIN_Y = round(H * 0.05)  # 上下各 5%，即 20px

# 小尺寸人物的细节只有特写的 1/3–1/6，固定阈值会先删掉眼高光、嘴角等 2–3px 结构。
# 因此按档位放宽：脸越小，提线阈值越低、去噪越小、允许交错的色差越大。
PARAMS = {
    "closeup": {"contrast": 30, "despeckle": 4, "dither_de": 10.0, "color_min": 6},
    "half": {"contrast": 24, "despeckle": 2, "dither_de": 12.0, "color_min": 4},
    "full": {"contrast": 22, "despeckle": 2, "dither_de": 12.0, "color_min": 3},
}


def clean_fg(fg):
    """保留主体与足够大的碎块，去掉右下角水印之类的孤立物。"""
    lab, n = label(fg)
    if n == 0:
        return fg
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    main = int(sizes.argmax())
    keep = lab == main
    thr = max(400, sizes[main] * 0.004)
    keep |= (sizes[lab] >= thr) & (lab > 0)
    return keep


def despeckle_colors(fills, min_px, material_idx=None, protect=None):
    """只合并同材质内的小色块；眼部与暗结构等保护像素不参与改写。"""
    cols, inv = np.unique(fills.reshape(-1, 3), axis=0, return_inverse=True)
    if len(cols) < 2:
        return fills
    color_idx = inv.reshape(fills.shape[:2])
    components = color_idx
    nkeys = len(cols)
    if material_idx is not None:
        # 同色但不同材质的像素属于不同连通域，禁止跨材质吞并。
        pairs = np.column_stack((color_idx.ravel(), material_idx.ravel()))
        _, pair_idx = np.unique(pairs, axis=0, return_inverse=True)
        components = pair_idx.reshape(fills.shape[:2])
        nkeys = int(components.max()) + 1
    out = color_idx.copy()
    if protect is None:
        protect = np.zeros(fills.shape[:2], dtype=bool)
    for key in range(nkeys):
        lab, n = label(components == key)
        if n == 0:
            continue
        sizes = np.bincount(lab.ravel())
        sizes[0] = 0
        for k in range(1, n + 1):
            if sizes[k] >= min_px:
                continue
            comp = lab == k
            if protect[comp].any():
                continue
            ring = binary_dilation(comp, iterations=1) & ~comp & ~protect
            if material_idx is not None:
                mid = material_idx[comp][0]
                ring &= material_idx == mid
            vals = out[ring]
            if vals.size == 0:
                continue
            out[comp] = np.bincount(vals, minlength=len(cols)).argmax()
    return cols[out]


def material_guard(rgb, idx, pal):
    """材质护栏：白衣不许吃肤色，皮肤中亮部不许落红棕暗槽。"""
    f = rgb.astype(np.float32) / 255.0
    mx = f.max(axis=-1)
    mn = f.min(axis=-1)
    sat = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    lum = 0.299 * f[..., 0] + 0.587 * f[..., 1] + 0.114 * f[..., 2]

    def recolor(mask, colors):
        if not mask.any():
            return
        ids = [i for i, c in enumerate(pal)
               if tuple(int(v) for v in c) in colors]
        if not ids:
            return
        sub = rgb[mask].astype(np.float32)
        d = np.linalg.norm(sub[:, None, :] - pal[ids][None, :, :].astype(np.float32), axis=-1)
        idx[mask] = np.array(ids)[d.argmin(1)]

    recolor((lum > 0.74) & (sat < 0.19), {(255, 255, 255), (170, 187, 170)})
    rd = [i for i, c in enumerate(pal) if tuple(int(v) for v in c) == (102, 51, 51)]
    if rd:
        recolor((idx == rd[0]) & (lum > 0.5),
                {(204, 136, 102), (221, 153, 119), (136, 85, 68)})
    return idx


def render(src_path, mode, name, pal=None, dither_de=None, color_min=None,
           material_region=False, smooth=False, guard=False, materials=None,
           material_baseline=None, return_debug=False, drawing_config=None):
    src = Image.open(src_path).convert("RGB")
    fg_hi = clean_fg(~bs.background_mask(src))
    bg_hi = ~fg_hi

    avail_h = H - 2 * MARGIN_Y
    if mode == "closeup":
        crop, bgc = src, bg_hi
        scale = min(W / src.width, avail_h / src.height)
        tw, th = round(src.width * scale), round(src.height * scale)
        ox, oy = (W - tw) // 2, (H - th) // 2
    else:
        ys, xs = np.where(fg_hi)
        pad = 8
        x0, x1 = max(0, xs.min() - pad), min(src.width, xs.max() + pad + 1)
        y0, y1 = max(0, ys.min() - pad), min(src.height, ys.max() + pad + 1)
        crop, bgc = src.crop((x0, y0, x1, y1)), bg_hi[y0:y1, x0:x1]
        th = avail_h
        tw = round(crop.width * th / crop.height)
        if tw > W - 2 * MARGIN_Y:
            tw = W - 2 * MARGIN_Y
            th = round(crop.height * tw / crop.width)
        ox, oy = (W - tw) // 2, H - th - MARGIN_Y

    mid = crop.resize((tw * 2, th * 2), Image.BOX)
    color = mid.resize((tw, th), Image.BOX)
    color = ImageEnhance.Color(color).enhance(1.08)
    if smooth:
        color = color.filter(ImageFilter.MedianFilter(5))
    rgb = bs.warm_gray_fix(np.array(color))

    bgsmall = np.array(
        Image.fromarray((bgc * 255).astype(np.uint8)).resize((tw, th), Image.BOX)
    ) > 127
    fg = ~bgsmall

    pal = bs.PALETTE if pal is None else np.asarray(pal, dtype=np.uint8)
    prm = PARAMS[mode]
    dde = prm["dither_de"] if dither_de is None else dither_de
    cmin = prm["color_min"] if color_min is None else color_min
    material_report = None
    classification_debug = None
    material_idx = None
    strict_mask = None
    if not material_region:
        idx0 = p98.fix_white_holes(p98.assign(rgb, pal), pal)
        if guard:
            idx0 = material_guard(rgb, idx0, pal)
        lab = p98.rgb_to_lab(pal.astype(np.float64))
        de = np.linalg.norm(lab[:, None, :] - lab[None, :, :], axis=-1)
        idx = bs.boundary_dither(idx0, allowed=de <= dde)
        fills = despeckle_colors(pal[idx], cmin)

    if material_region:
        if materials:
            fills, mstats, classification_debug = matregion.render_spec(
                rgb, fg, pal, materials, tier=mode, return_debug=True,
                drawing_config=drawing_config)
            material_idx = classification_debug["material_idx"]
            despeckle_idx = material_idx.copy()
            despeckle_idx[~fg] = -2  # 暗结构与透明背景不能互相吞并。
            fills = despeckle_colors(
                fills, cmin, material_idx=despeckle_idx,
                protect=classification_debug["protected"])
            material_report = lint.lint_materials(
                material_idx, materials, fg, material_baseline)
            material_report["classification"] = classification_debug["report"]
            material_report["baseline_source"] = (
                material_baseline.get("source") if material_baseline else None)
            strict_mask = np.kron(
                drawing.white_line_strict_mask(material_idx, fg, materials),
                np.ones((2, 2), dtype=bool))
        else:
            fills, mstats = matregion.render(rgb, fg, pal)
            fills = despeckle_colors(fills, cmin)
        print("materials", mstats)

    candidate, _, features = v7.line_layer(
        mid, (tw, th), contrast=prm["contrast"], strict_mask=strict_mask,
        return_features=True)
    line_layers = drawing.build_line_layers(
        candidate, fg, material_idx=material_idx, materials=materials,
        ink_core=features["ink_core"], contrast_edge=features["contrast_edge"],
        min_size=prm["despeckle"])
    lmask = line_layers.mask
    fills[lmask] = (0, 0, 0)
    if material_report is not None and "cloth_layers" in classification_debug:
        drawing_lint = lint.lint_drawing(
            fills, material_idx, materials, classification_debug["cloth_layers"],
            classification_debug["drawing_report"], config=drawing_config,
            line_mask=lmask)
        material_report["checks"].update(drawing_lint["checks"])
        material_report["drawing"] = classification_debug["drawing_report"]
        material_report["pass"] = all(
            item["pass"] for item in material_report["checks"].values())

    alpha = np.where(bgsmall, 0, 255).astype(np.uint8)
    sprite = Image.fromarray(np.dstack([fills, alpha]).astype(np.uint8), "RGBA")

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    canvas.alpha_composite(sprite, (ox, oy))

    outdir = ROOT / "output"
    canvas.save(outdir / f"{name}.png")
    white = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    white.alpha_composite(canvas)
    white.convert("RGB").save(outdir / f"{name}_white.png")
    white.convert("RGB").resize((W * 2, H * 2), Image.Resampling.NEAREST).save(
        outdir / f"{name}_x2.jpg", quality=94, subsampling=0
    )

    a = np.array(white.convert("RGB")).astype(np.int16)
    chroma = a.max(2) - a.min(2)
    lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    midgray = int(((chroma < 12) & (lum > 20) & (lum < 235)).sum())
    blk = np.all(a == 0, 2)
    runs = []
    for y in range(H):
        c = 0
        for v in blk[y]:
            if v:
                c += 1
            elif c:
                runs.append(c)
                c = 0
    print(name, "size", (tw, th), "colors", len(np.unique(np.array(white.convert("RGB")).reshape(-1, 3), axis=0)),
          "midgray", midgray, "1px", runs.count(1), "2px", runs.count(2))
    result = white.convert("RGB")
    if return_debug:
        debug = {
            "material_report": material_report,
            "fills": fills.copy(),
            "fg": fg,
            "line_mask": lmask.copy(),
            "line_candidate": line_layers.candidate.copy(),
            "line_kind": line_layers.kind.copy(),
            "line_protected": line_layers.protected.copy(),
            "ink_core": line_layers.ink_core.copy(),
            "contrast_edge": line_layers.contrast_edge.copy(),
            "sprite_box": (ox, oy, tw, th),
        }
        if classification_debug is not None:
            debug.update({k: classification_debug[k] for k in
                          ("raw_idx", "material_idx", "override_masks", "protected")})
            for key in ("cloth_layers", "cloth_tones", "cloth_surface",
                        "cloth_surface_tones", "drawing_report"):
                if key in classification_debug:
                    debug[key] = classification_debug[key]
        return result, debug
    return result


def main():
    import argparse
    ap = argparse.ArgumentParser(description="三档构图渲染")
    ap.add_argument("--palette", default="", help="palette98.py 生成的 JSON")
    ap.add_argument("--closeup-palette", default="", help="特写单独用色板（缺省同 --palette）")
    ap.add_argument("--prefix", default="akira_asset", help="输出文件名前缀")
    ap.add_argument("--tier", required=True, choices=("closeup", "half", "full"),
                    help="只渲染一档；禁止一次出三档")
    ap.add_argument("--dither-de", type=float, default=None,
                    help="覆盖该档抖动阈值；0 表示关闭抖动")
    ap.add_argument("--color-min", type=int, default=None,
                    help="覆盖该档孤立色块合并阈值（px）")
    ap.add_argument("--material-region", action="store_true",
                    help="按材质区域上色（默认关闭）")
    ap.add_argument("--smooth", action="store_true",
                    help="上色前做 5px 中值滤波（默认关闭）")
    ap.add_argument("--guard", action="store_true",
                    help="启用旧的逐像素材质护栏（默认关闭）")
    ap.add_argument("--closeup", default=str(SRC / "akira_bust_hi.jpg"))
    ap.add_argument("--half", default=str(SRC / "akira_half_hi.jpg"))
    ap.add_argument("--full", default=str(SRC / "akira_full_hi.jpg"))
    args = ap.parse_args()

    pal = None
    pal_closeup = None
    if args.palette:
        import palette98
        pal = palette98.load(args.palette)
    if args.closeup_palette:
        import palette98
        pal_closeup = palette98.load(args.closeup_palette)

    src = {"closeup": args.closeup, "half": args.half, "full": args.full}[args.tier]
    pal_tier = (pal_closeup or pal) if args.tier == "closeup" else pal
    render(src, args.tier, f"{args.prefix}_{args.tier}", pal_tier, args.dither_de,
           args.color_min, args.material_region, args.smooth, args.guard)


if __name__ == "__main__":
    main()
