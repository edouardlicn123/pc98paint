# -*- coding: utf-8 -*-
"""按材质区域上色：先分割材质，再在各自白名单内取色。

设计要点（2026-11-22 方案）：
1. 白衣不是靠亮度阈值，而是靠“中性白 + 与藏青相邻”识别，避免白领吃肤色；
2. 每种材质只允许自己的色板槽位，跨材质取色被禁止；
3. 布料/白衣/皮肤按材质内亮度中位数分带，得到大块硬边，不做逐像素抖动；
4. 黑色只给线层和真正的暗结构（瞳孔、眼镜），布料阴影不落黑。
"""
import numpy as np
from scipy.ndimage import (binary_closing, binary_dilation, binary_opening,
                           distance_transform_edt, gaussian_filter, label)

import drawing

SKIN, WHITE, NAVY, HAIR, GREEN, DARK = 1, 2, 3, 4, 5, 6


def _hsv(a):
    mx = a.max(axis=-1)
    mn = a.min(axis=-1)
    d = mx - mn
    sat = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0.0)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    hue = np.zeros_like(mx)
    m = (mx == r) & (d > 0)
    hue[m] = ((g - b) / np.maximum(d, 1e-6))[m] % 6
    m = (mx == g) & (d > 0)
    hue[m] = ((b - r) / np.maximum(d, 1e-6) + 2)[m]
    m = (mx == b) & (d > 0)
    hue[m] = ((r - g) / np.maximum(d, 1e-6) + 4)[m]
    hue *= 60.0
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return hue, sat, lum


def classify(rgb, fg):
    """返回材质图：0 背景，1 皮肤，2 白衣，3 藏青，4 头发/棕，5 绿，6 暗结构。"""
    a = rgb.astype(np.float32) / 255.0
    hue, sat, lum = _hsv(a)

    dark = fg & (lum < 0.16)
    green = fg & (hue > 70) & (hue < 175) & (sat > 0.22) & (lum < 0.92)
    navy = fg & (hue > 185) & (hue < 265) & (sat > 0.15) & (lum < 0.62)

    # 中性白做种子；再把“小面积、贴着白衣”的暖色块并进白衣。
    # 白领的米色阴影是这种小碎块，而脸/脖子是大连通域，不会被吞进来。
    white = fg & (sat < 0.10) & (lum > 0.88)
    for _ in range(2):
        other = fg & ~white & (lum > 0.55)
        lab, n = label(other)
        wd = binary_dilation(white, iterations=1)
        for k in range(1, n + 1):
            comp = lab == k
            if comp.sum() > 400:
                continue
            ring = binary_dilation(comp, iterations=1) & ~comp
            if ring.sum() and (ring & wd).sum() / ring.sum() >= 0.30:
                white |= comp

    skin = fg & ~dark & ~green & ~navy & ~white & (lum > 0.60)

    # 眼内高光：被虹膜/眼线包围的小亮块，一律归白衣，且后面不参与分带。
    iris_dark = fg & (((lum < 0.50) & (sat > 0.12)) | (lum < 0.16))
    lab2, n2 = label(fg & ~white & (lum > 0.72) & (sat < 0.45))
    for k in range(1, n2 + 1):
        comp = lab2 == k
        if comp.sum() > 16:
            continue
        ring = binary_dilation(comp, iterations=1) & ~comp
        if ring.sum() and (ring & iris_dark).sum() / ring.sum() >= 0.70:
            white |= comp
    brown = fg & ~dark & ~green & ~navy & ~white & ~skin

    mat = np.zeros(fg.shape, np.uint8)
    mat[skin] = SKIN
    mat[white] = WHITE
    mat[navy] = NAVY
    mat[green] = GREEN
    mat[brown] = HAIR
    mat[dark] = DARK
    return mat


def _absorb_small(mat, min_px=12):
    """把面积过小的材质碎块并入邻域多数，避免锯齿状材质边。"""
    out = mat.copy()
    for mid in (SKIN, WHITE, NAVY, HAIR, GREEN, DARK):
        lab, n = label(out == mid)
        if n == 0:
            continue
        sizes = np.bincount(lab.ravel())
        sizes[0] = 0
        for k in range(1, n + 1):
            if sizes[k] >= min_px:
                continue
            comp = lab == k
            ring = binary_dilation(comp, iterations=1) & ~comp
            vals = out[ring]
            vals = vals[vals > 0]
            if vals.size:
                out[comp] = np.bincount(vals).argmax()
    return out


def _ids(pal):
    return {tuple(int(v) for v in c): i for i, c in enumerate(pal)}


def paint(rgb, fg, mat, pal):
    """在材质白名单内取色，按材质内亮度分带。"""
    ids = _ids(pal)
    _, _, lum = _hsv(rgb.astype(np.float32) / 255.0)
    fills = np.zeros(rgb.shape, np.uint8)

    def put(mask, color):
        if mask.any():
            fills[mask] = pal[ids[color]]

    def bands(mask, color_base, color_shadow, q):
        """按材质内亮度分位切两档：先平滑亮度，取最暗 q% 为暗档，得到大块硬边。"""
        if not mask.any():
            return
        sm = gaussian_filter(lum, 3.0)
        thr = float(np.percentile(sm[mask], q))
        shadow = mask & (sm < thr)
        shadow = binary_opening(shadow, iterations=1) & mask
        put(mask & ~shadow, color_base)
        put(shadow, color_shadow)

    def rim_bands(mask, color_base, color_shadow):
        """制服专用：只在远离光源的右/下轮廓内侧留暗带，内部不产生孤立暗块。"""
        if not mask.any():
            return
        ys, xs = np.where(mask)
        y0, y1 = ys.min(), ys.max()
        H = y1 - y0 + 1
        k = max(2, int(round(mask.shape[1] * 0.02)))
        # 闭运算跨过 1px 黑线，距离只量到真正的剪影轮廓，不沿褶线长暗边
        sil = binary_closing(mask, structure=np.ones((3, 3)))
        # 向外复制边缘再算距离：裁切边不被当成轮廓（不长横向暗带），
        # 但侧面的暗带可以一直延伸到底部，不会半路截断。
        p = k + 2
        dist = distance_transform_edt(np.pad(sil, p, mode='edge'))[p:-p, p:-p]
        YY, XX = np.mgrid[0:mask.shape[0], 0:mask.shape[1]]
        zone = XX >= xs.mean()
        shadow = mask & (dist <= k) & zone
        # 底部裁切带里只保留从上方连续延伸下来的暗带；
        # 只在裁切处新长出来的横向暗带一律删掉。
        fy, _ = np.where(fg)
        cut = YY >= fy.max() - (k + 1)
        # 裁切带里只允许贴着右轮廓的竖向暗带存在，横向的新暗带一律删掉
        right = np.full(mask.shape[0], -10 ** 6)
        for y in range(mask.shape[0]):
            xs_row = np.where(mask[y])[0]
            if xs_row.size:
                right[y] = xs_row.max()
        shadow &= (~cut) | (XX >= right[:, None] - k)
        lab, n = label(shadow)
        for i in range(1, n + 1):
            comp = lab == i
            if not (comp & ~cut).any():
                shadow &= ~comp
        put(mask & ~shadow, color_base)
        put(shadow, color_shadow)

    m = mat == WHITE
    lab, n = label(m)
    big = np.zeros_like(m)
    for k in range(1, n + 1):
        comp = lab == k
        if comp.sum() >= 200:
            big |= comp
    bands(big, (255, 255, 255), (170, 187, 170), 12)
    put(m & ~big, (255, 255, 255))

    m = mat == SKIN
    if m.any():
        med = float(np.median(lum[m]))
        put(m & (lum >= med * 0.95), (255, 221, 187))
        put(m & (lum >= med * 0.80) & (lum < med * 0.95), (221, 153, 119))
        put(m & (lum < med * 0.80), (204, 136, 102))

    m = mat == NAVY
    rim_bands(m, (34, 68, 119), (34, 51, 85))

    m = mat == HAIR
    bands(m, (136, 85, 68), (102, 51, 51), 35)

    m = mat == GREEN
    bands(m, (119, 170, 102), (102, 119, 102), 30)

    m = mat == DARK
    put(m, (0, 0, 0))

    # 材质内还有漏网像素时，归到该材质最接近的白名单槽
    allowed = {
        WHITE: [(255, 255, 255), (170, 187, 170)],
        SKIN: [(255, 221, 187), (221, 153, 119), (204, 136, 102)],
        NAVY: [(34, 68, 119), (34, 51, 85)],
        HAIR: [(136, 85, 68), (102, 51, 51)],
        GREEN: [(119, 170, 102), (102, 119, 102)],
        DARK: [(0, 0, 0)],
    }
    for mid, cols in allowed.items():
        hole = (mat == mid) & (fills.sum(axis=-1) == 0)
        if not hole.any():
            continue
        cand = np.array([pal[ids[c]] for c in cols], np.float32)
        sub = rgb[hole].astype(np.float32)
        d = np.linalg.norm(sub[:, None, :] - cand[None, :, :], axis=-1)
        fills[hole] = cand[d.argmin(1)].astype(np.uint8)

    return fills


def render(rgb, fg, pal, materials=None):
    if materials:
        return render_spec(rgb, fg, pal, materials)
    mat = classify(rgb, fg)
    mat = _absorb_small(mat)
    fills = paint(rgb, fg, mat, pal)
    stats = {k: int((mat == v).sum()) for k, v in
             (("skin", SKIN), ("white", WHITE), ("navy", NAVY),
              ("hair", HAIR), ("green", GREEN), ("dark", DARK))}
    return fills, stats


# ---------------- spec 驱动（每个角色一份 materials） ----------------

def _hex_rgb(s):
    s = s.lstrip("#")
    return np.array([int(s[i:i + 2], 16) for i in (0, 2, 4)], np.float32)


def _lab_img(rgb):
    c = rgb.astype(np.float32) / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124, 0.3576, 0.1805],
                  [0.2126, 0.7152, 0.0722],
                  [0.0193, 0.1192, 0.9505]], np.float32)
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883], np.float32)
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16,
                     500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])], -1)


def _classification_limits(tier):
    """面积阈值随档位缩放，避免全身档删细节、特写档留下大块误分类。"""
    area_scale = {"closeup": 4.0, "half": 1.0, "full": 0.35}.get(tier)
    if area_scale is None:
        raise ValueError(f"未知立绘档位: {tier}")
    dilation = {"closeup": 8, "half": 4, "full": 2}[tier]
    return {
        "skin_component_max": max(4, int(round(200 * area_scale))),
        "eye_dilation": dilation,
        "eye_bright_max": max(4, int(round(100 * area_scale))),
        "fragment_max": max(2, int(round(12 * area_scale))),
    }


def _material_stats(idx, materials):
    return {m["id"]: int((idx == i).sum()) for i, m in enumerate(materials)}


def classify_materials(rgb, fg, materials, tier="half", return_debug=False):
    """最近色候选 → 暗部/眼部保护 → 皮肤白衣竞争 → 非保护碎块吸收。"""
    lab = _lab_img(rgb)
    n = len(materials)
    limits = _classification_limits(tier)
    dist = np.full(fg.shape + (n,), 1e9, np.float32)
    for i, m in enumerate(materials):
        for ref in m.get("refs", []):
            c = _lab_img(_hex_rgb(ref)[None, None, :])[0, 0]
            d = ((lab - c) ** 2).sum(-1)
            dist[..., i] = np.minimum(dist[..., i], d)

    idx = dist.argmin(-1).astype(np.int16)
    lum = rgb.astype(np.float32).mean(-1)
    dark = fg & (lum < 40)
    idx[~fg] = -1
    idx[dark] = -1  # 暗结构交给线层，后续规则不得覆盖。
    raw_idx = idx.copy()

    mx = rgb.max(-1).astype(np.float32)
    mn = rgb.min(-1).astype(np.float32)
    sat = (mx - mn) / np.maximum(mx, 1.0)
    white_i = [i for i, m in enumerate(materials) if m.get("role") == "white"]
    skin_i = [i for i, m in enumerate(materials) if m.get("role") == "skin"]
    eye_i = [i for i, m in enumerate(materials) if m.get("role") == "eye"]
    protected = dark.copy()
    masks = {name: np.zeros(fg.shape, bool) for name in
             ("eye_expansion", "eye_highlight", "skin_recovery",
              "white_seed", "fragment_absorption")}

    # 先锁定眼睛与暗结构；后面的皮肤/白衣规则不能抢回这些像素。
    if eye_i:
        seed = np.isin(idx, eye_i)
        if seed.any():
            hue, sat_h, _ = _hsv(rgb.astype(np.float32) / 255.0)
            near = binary_dilation(seed, iterations=limits["eye_dilation"]) & fg
            teal = near & (hue > 120) & (hue < 210) & (sat_h > 0.25) & ~protected
            before = idx.copy()
            idx[teal] = eye_i[0]
            masks["eye_expansion"] = teal & (before != idx)

            seed = np.isin(idx, eye_i)
            dark_ring = fg & (lum < 60)
            bright = fg & (sat < 0.25) & (lum > 205)
            lab_b, nb = label(bright)
            for k in range(1, nb + 1):
                comp = lab_b == k
                if comp.sum() > limits["eye_bright_max"]:
                    continue
                ring = binary_dilation(comp, iterations=1) & ~comp
                if ring.sum() and ((ring & (seed | dark_ring)).sum()
                                   / ring.sum()) >= 0.55:
                    masks["eye_highlight"] |= comp
                    idx[comp] = white_i[0] if white_i else eye_i[0]
            protected |= np.isin(idx, eye_i) | masks["eye_highlight"]

    if white_i and skin_i:
        # 只回收被既有皮肤包围的小块；大片白衣即使最近非白材质是皮肤也不回收。
        nonwhite = dist.copy()
        nonwhite[..., white_i] = 1e9
        alt = nonwhite.argmin(-1)
        skin_like = np.isin(alt, skin_i)
        skin_seed = np.isin(idx, skin_i)
        candidate = np.isin(idx, white_i) & skin_like & fg & ~protected
        lab_c, nc = label(candidate)
        for k in range(1, nc + 1):
            comp = lab_c == k
            if comp.sum() > limits["skin_component_max"]:
                continue
            ring = binary_dilation(comp, iterations=2) & ~comp
            if ring.sum() and (ring & skin_seed).sum() / ring.sum() >= 0.35:
                masks["skin_recovery"] |= comp & (idx != alt)
                idx[comp] = alt[comp]

    if white_i:
        # 已被识别为皮肤或眼部高光的亮部，不允许再被白色种子覆盖。
        white_seed = (fg & (sat < 0.10) & (lum > 232)
                      & ~np.isin(idx, skin_i) & ~protected)
        before = idx.copy()
        idx[white_seed] = white_i[0]
        masks["white_seed"] = white_seed & (before != idx)

    # 最后的碎块吸收同样受眼部/暗部保护，不能静默撤销前面的规则。
    out = idx.copy()
    for i in range(n):
        comp_lab, ncomp = label(out == i)
        for k in range(1, ncomp + 1):
            comp = comp_lab == k
            if comp.sum() >= limits["fragment_max"] or (comp & protected).any():
                continue
            near = binary_dilation(comp, iterations=2) & fg & ~comp & ~protected
            vals = out[near]
            vals = vals[vals >= 0]
            if vals.size:
                new_id = np.bincount(vals).argmax()
                masks["fragment_absorption"] |= comp & (out != new_id)
                out[comp] = new_id

    if not return_debug:
        return out
    report = {
        "tier": tier,
        "thresholds": limits,
        "overrides": {name: int(mask.sum()) for name, mask in masks.items()},
        "raw_stats": _material_stats(raw_idx, materials),
        "final_stats": _material_stats(out, materials),
    }
    debug = {
        "raw_idx": raw_idx,
        "material_idx": out.copy(),
        "override_masks": masks,
        "protected": protected,
        "report": report,
    }
    return out, debug


def _hair_highlight(mask):
    """高光带：顶部轮廓内侧 20%-32% 头高处，取受光侧，断成 2-3 段。"""
    ys, xs = np.where(mask)
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    H = y1 - y0 + 1
    row = min(y1, y0 + max(1, int(0.12 * H)))
    rhs = np.where(mask[row])[0]
    hw = int(rhs.max() - rhs.min() + 1) if rhs.size else 40
    head_h = max(30.0, hw * 0.95)
    lo, hi = 0.20 * head_h, 0.32 * head_h
    top = np.full(mask.shape[1], 10 ** 6, np.int32)
    for x in range(x0, x1 + 1):
        col = np.where(mask[:, x])[0]
        if col.size:
            top[x] = col.min()
    YY, XX = np.mgrid[0:mask.shape[0], 0:mask.shape[1]]
    dy = YY - top[None, :]
    band = mask & (dy >= lo) & (dy <= hi) & (XX <= x0 + 0.78 * (x1 - x0))
    band = binary_opening(band, structure=np.ones((2, 2)))
    lab, n = label(band)
    keep = np.zeros_like(band)
    for i in range(1, n + 1):
        comp = lab == i
        if comp.sum() >= 20:
            keep |= comp
    return keep


def _hair_shadow(mask, fg, ratio=0.02):
    """暗带：发块下沿/内侧，远离头顶。"""
    k = max(2, int(round(mask.shape[1] * ratio)))
    sil = binary_closing(mask, structure=np.ones((3, 3)))
    p = k + 2
    dist = distance_transform_edt(np.pad(sil, p, mode="edge"))[p:-p, p:-p]
    ys, _ = np.where(mask)
    y0, y1 = int(ys.min()), int(ys.max())
    YY = np.mgrid[0:mask.shape[0], 0:mask.shape[1]][0]
    shadow = mask & (dist <= k) & (YY > y0 + 0.45 * (y1 - y0))
    return shadow


def render_spec(rgb, fg, pal, materials, tier="half", return_debug=False,
                drawing_config=None):
    """按 spec.materials 上色：颜色来自各材质 refs，全部吸附到 16 色板。"""
    pal = np.asarray(pal, np.uint8)
    ids = _ids(pal)

    def snap(color):
        c = np.asarray(color, np.float32)
        d = ((pal.astype(np.float32) - c) ** 2).sum(1)
        return pal[int(np.argmin(d))]

    def nearest_of(mask, refs):
        cand = np.array([snap(r) for r in refs], np.float32)
        sub = rgb[mask].astype(np.float32)
        d = ((sub[:, None, :] - cand[None, :, :]) ** 2).sum(-1)
        return cand[d.argmin(1)].astype(np.uint8)

    if return_debug:
        idx, debug = classify_materials(
            rgb, fg, materials, tier=tier, return_debug=True)
    else:
        idx = classify_materials(rgb, fg, materials, tier=tier)
    lum = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]) / 255.0

    # 五类布料层只改变层内着色，不回写材质分类。
    cloth = drawing.build_cloth_layers(rgb, fg, idx, materials, drawing_config)

    fills = np.zeros(rgb.shape, np.uint8)
    for i, m in enumerate(materials):
        mask = idx == i
        if not mask.any():
            continue
        role = m.get("role", "flat")
        refs = [_hex_rgb(s) for s in m.get("refs", ["#ffffff"])]
        base = snap(refs[0])
        shadow = snap(refs[-1])
        if role in ("white", "cloth"):
            fills[mask] = base
        elif role == "hair":
            hi = _hair_highlight(mask)
            sh = _hair_shadow(mask, fg)
            mid = snap(refs[1]) if len(refs) > 2 else base
            fills[mask] = mid
            fills[sh] = shadow
            fills[hi] = base
        elif role == "skin":
            # 皮肤族内三档，禁止跨族吸附。
            # 以受光色为基色，阴影只出现在右轮廓暗带和确实偏暗的区域（下巴/发下），
            # 避免逐像素亮度分位在脸上切出碎斑。
            tones = [snap(r) for r in refs]
            base_t = tones[0]
            mid_t = tones[1] if len(tones) > 2 else tones[-1]
            deep_t = tones[-1]
            w = mask.astype(np.float32)
            sm = gaussian_filter(lum * w, 2.0) / np.maximum(
                gaussian_filter(w, 2.0), 1e-6)
            rim = drawing.rim_shadow(mask, fg, ratio=0.03)
            low = mask & (sm <= np.percentile(sm[mask], 16))
            sh = (rim | low) & mask
            l, c = label(sh & ~rim)
            for j in range(1, c + 1):
                comp = l == j
                if comp.sum() < 16:
                    sh &= ~comp
            fills[mask] = base_t
            fills[sh] = mid_t
            deep = mask & (sm <= np.percentile(sm[mask], 6))
            l, c = label(deep)
            for j in range(1, c + 1):
                comp = l == j
                if comp.sum() < 12:
                    deep &= ~comp
            fills[deep] = deep_t
        else:
            fills[mask] = nearest_of(mask, refs)

    def put_tone(i, mask, tone):
        refs = materials[i].get("refs", ["#ffffff"])
        fills[mask] = snap(_hex_rgb(refs[int(tone)]))

    def apply_layer(name):
        layer = getattr(cloth, name)
        tone_map = cloth.tones[name]
        for i, material in enumerate(materials):
            owned = layer & (idx == i)
            for tone in np.unique(tone_map[owned]):
                if tone >= 0:
                    put_tone(i, owned & (tone_map == tone), tone)

    apply_layer("form")
    # 材质图案位于体积暗面之上、褶皱与投影之下。
    for material_id, layer in cloth.surface.items():
        i = next(j for j, m in enumerate(materials) if m["id"] == material_id)
        tone_map = cloth.surface_tones[material_id]
        for tone in np.unique(tone_map[layer]):
            if tone >= 0:
                put_tone(i, layer & (tone_map == tone), tone)
    apply_layer("fold")
    apply_layer("highlight")
    apply_layer("occlusion")

    dark = fg & (idx < 0)
    if dark.any():
        fills[dark] = pal[ids[(0, 0, 0)]] if (0, 0, 0) in ids else 0

    hole = fg & (fills.sum(-1) == 0)
    if hole.any():
        sub = rgb[hole].astype(np.float32)
        d = ((sub[:, None, :] - pal.astype(np.float32)[None, :, :]) ** 2).sum(-1)
        fills[hole] = pal[d.argmin(1)].astype(np.uint8)

    stats = _material_stats(idx, materials)
    if return_debug:
        debug["protected"] = debug["protected"] | cloth.protected
        debug["cloth_layers"] = cloth.masks()
        debug["cloth_tones"] = cloth.tones
        debug["cloth_surface"] = cloth.surface
        debug["cloth_surface_tones"] = cloth.surface_tones
        debug["drawing_report"] = cloth.stats
        return fills, stats, debug
    return fills, stats
