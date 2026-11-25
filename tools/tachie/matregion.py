# -*- coding: utf-8 -*-
"""按材质区域上色：先分割材质，再在各自白名单内取色。

设计要点（2026-11-22 方案）：
1. 白衣不是靠亮度阈值，而是靠“中性白 + 与藏青相邻”识别，避免白领吃肤色；
2. 每种材质只允许自己的色板槽位，跨材质取色被禁止；
3. 布料/白衣/皮肤按材质内亮度中位数分带，得到大块硬边，不做逐像素抖动；
4. 黑色只给线层和真正的暗结构（瞳孔、眼镜），布料阴影不落黑。
"""
import numpy as np
from scipy.ndimage import (binary_closing, binary_dilation,
                           binary_opening, distance_transform_edt,
                           gaussian_filter, label, uniform_filter)

import drawing
import shading

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


def _classification_limits(tier, scale=1.0):
    """面积阈值随档位缩放，避免全身档删细节、特写档留下大块误分类。

    ``scale`` converts 640x400 pixel units to a higher detection resolution:
    areas scale by square, radii by the factor itself.
    """
    area_scale = {"closeup": 4.0, "half": 1.0, "full": 0.35}.get(tier)
    if area_scale is None:
        raise ValueError(f"未知立绘档位: {tier}")
    if scale <= 0:
        raise ValueError(f"scale 必须为正: {scale}")
    dilation = {"closeup": 8, "half": 4, "full": 2}[tier]
    dilation = max(1, int(round(dilation * scale)))
    area_scale *= scale * scale
    return {
        "skin_component_max": max(4, int(round(600 * area_scale))),
        "eye_dilation": dilation,
        "eye_bright_max": max(4, int(round(100 * area_scale))),
        "fragment_max": max(2, int(round(12 * area_scale))),
    }


def _material_stats(idx, materials):
    return {m["id"]: int((idx == i).sum()) for i, m in enumerate(materials)}


def _absorb_ink_seams(idx, fg, dark, materials, protected):
    """Reassign 1-3 px runs fenced by ink to the white material on both sides.

    A white fold seam has no room for its own colour; ink antialiasing drags
    the sample toward the skin ramp and colour distance alone classifies it as
    skin (v10.2 ①).  Only runs bounded by ink on both sides and flanked by the
    same white material are moved, so skin islands and detached hands stay.
    """
    white_i = [i for i, m in enumerate(materials) if m.get("role") == "white"]
    skin_i = [i for i, m in enumerate(materials) if m.get("role") == "skin"]
    moved = np.zeros(idx.shape, bool)
    if not white_i or not skin_i:
        return idx, moved
    out = idx.copy()
    # Any unclassified pixel inside the silhouette is line art, not a gap.
    ink = dark | ((idx < 0) & fg)
    for transpose in (False, True):
        view = out.T if transpose else out
        ink_v = ink.T if transpose else ink
        prot = protected.T if transpose else protected
        fg_v = fg.T if transpose else fg
        for y in range(view.shape[0]):
            row = view[y]
            x, n = 0, row.shape[0]
            while x < n:
                if ink_v[y, x] or not fg_v[y, x]:
                    x += 1
                    continue
                start = x
                while x < n and not ink_v[y, x] and fg_v[y, x]:
                    x += 1
                end = x
                if not 1 <= end - start <= 3:
                    continue
                left, right = start - 1, end
                if left < 0 or right >= n:
                    continue
                if not ink_v[y, left] or not ink_v[y, right]:
                    continue
                lx = left - 1
                while lx >= 0 and ink_v[y, lx]:
                    lx -= 1
                rx = right + 1
                while rx < n and ink_v[y, rx]:
                    rx += 1
                if lx < 0 or rx >= n:
                    continue
                near = row[lx]
                if near != row[rx] or near not in white_i:
                    continue
                run = row[start:end]
                take = np.isin(run, skin_i) & ~prot[y, start:end]
                if not take.any():
                    continue
                run[take] = near
                row[start:end] = run
                target = moved.T if transpose else moved
                target[y, start:end] = take
    return out, moved


def _absorb_enclosed_skin(idx, fg, dark, materials, protected):
    """Thin skin fragments fenced entirely by white and ink are fold cores.

    A diagonal crease has no row/column run to absorb it (v10.2 ①); the only
    reliable signal is topology: a 1-2 px sliver whose whole boundary is the
    blouse and its ink line.  Real skin islands touch hair, background or a
    second material and are left alone.
    """
    white_i = [i for i, m in enumerate(materials) if m.get("role") == "white"]
    skin_i = [i for i, m in enumerate(materials) if m.get("role") == "skin"]
    moved = np.zeros(idx.shape, bool)
    if not white_i or not skin_i:
        return idx, moved
    skin = np.isin(idx, skin_i) & fg & ~protected
    if not skin.any():
        return idx, moved
    white = np.isin(idx, white_i) & fg
    ink = dark | ((idx < 0) & fg)
    white_or_ink = white | ink
    out = idx.copy()
    lab, n = label(skin)
    for k in range(1, n + 1):
        comp = lab == k
        area = int(comp.sum())
        if area < 2 or area > 160:
            continue
        if float(distance_transform_edt(comp).max()) > 2.5:
            continue
        ring = binary_dilation(comp, iterations=1) & ~comp
        total = int(ring.sum())
        if not total:
            continue
        if int((ring & white_or_ink).sum()) < 0.95 * total:
            continue
        near = idx[ring & white]
        target = int(np.bincount(near).argmax()) if near.size else white_i[0]
        out[comp] = target
        moved |= comp
    return out, moved


def _recover_pale_skin(idx, fg, rgb, materials, protected, face=None,
                       owned=None):
    """Grow real skin into near-white pale skin.

    Pale skin (chest under the chin, inner forearms) is only a few Lab units
    away from white, so nearest-colour assignment picks blouse or hair.  A pale
    skin pixel is warm (R > G >= B), bright and low-saturation; white cloth is
    cooler (R <= G) and its folds are green, hair is more saturated.  Only
    pixels contiguous with real skin are taken, and the face is skipped so eye
    and cheek speculars stay white.

    ``owned`` marks pixels inside a garment band that explicitly claims them
    (e.g. the cream blouse torso); those must stay with the garment even
    though they touch the neck.
    """
    skin_i = [i for i, m in enumerate(materials) if m.get("role") == "skin"]
    moved = np.zeros(idx.shape, bool)
    if not skin_i:
        return idx, moved
    r = rgb[..., 0].astype(np.int16)
    g = rgb[..., 1].astype(np.int16)
    b = rgb[..., 2].astype(np.int16)
    lum = rgb.astype(np.float32).mean(-1)
    mx = rgb.max(-1).astype(np.float32)
    mn = rgb.min(-1).astype(np.float32)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    skin = np.isin(idx, skin_i)
    pale = (fg & ~skin & ~protected
            & (r > g) & (g >= b - 2)
            & (r - b >= 12) & (lum >= 195) & (sat <= 0.17))
    if face is not None:
        pale &= ~face
    if owned is not None:
        pale &= ~owned
    grow = skin.copy()
    for _ in range(24):
        step = pale & binary_dilation(grow, iterations=1)
        if not step.any():
            break
        grow |= step
        moved |= step
    if moved.any():
        idx = idx.copy()
        idx[moved] = skin_i[0]
    return idx, moved


def _recover_skin_specks(idx, fg, materials, protected, avoid=None,
                         max_size=200, min_skin_ring=0.75,
                         max_white_ring=0.10):
    """Turn small neutral highlights enclosed by skin back into skin.

    A skin highlight is almost pure white, so the brightness competition sends
    it to blouse; the cloth shading then tints the speck green.  Colour cannot
    separate it from a cloth specular, but topology can: a tiny white island
    whose ring is nearly all skin is a skin highlight, while cloth speculars
    sit inside cloth.  ``avoid`` keeps eye/nose speculars white.
    """
    skin_i = [i for i, m in enumerate(materials) if m.get("role") == "skin"]
    white_i = [i for i, m in enumerate(materials) if m.get("role") == "white"]
    moved = np.zeros(idx.shape, bool)
    if not skin_i or not white_i:
        return idx, moved
    skin = np.isin(idx, skin_i)
    white = np.isin(idx, white_i)
    lab_w, n_w = label(white & fg)
    for k in range(1, n_w + 1):
        comp = lab_w == k
        if comp.sum() > max_size or (comp & protected).any():
            continue
        if avoid is not None and (comp & avoid).any():
            continue
        ring = binary_dilation(comp, iterations=2) & ~comp & fg
        if not ring.sum():
            continue
        if skin[ring].mean() < min_skin_ring or white[ring].mean() > max_white_ring:
            continue
        moved |= comp
    if moved.any():
        idx = idx.copy()
        idx[moved] = skin_i[0]
    return idx, moved


# Added to a material's squared-Lab distance when a pixel falls outside the
# material's allowed height band (see ``region_prior``).
REGION_PENALTY = 600.0


def classify_materials(rgb, fg, materials, tier="half", return_debug=False,
                       scale=1.0, region_prior=None):
    """最近色候选 → 暗部/眼部保护 → 皮肤白衣竞争 → 非保护碎块吸收。"""
    lab = _lab_img(rgb)
    n = len(materials)
    limits = _classification_limits(tier, scale)
    dist = np.full(fg.shape + (n,), 1e9, np.float32)
    for i, m in enumerate(materials):
        for ref in m.get("refs", []):
            c = _lab_img(_hex_rgb(ref)[None, None, :])[0, 0]
            d = ((lab - c) ** 2).sum(-1)
            dist[..., i] = np.minimum(dist[..., i], d)

    owned = np.zeros(fg.shape, bool)
    if region_prior:
        # Soft vertical prior: two garments can share almost identical browns
        # (sailor collar vs pleated skirt), so colour alone cannot separate
        # them.  Pixels outside a material's allowed height band receive a
        # constant penalty, which still lets an unmistakable colour win.
        # A negative bonus inside the band only applies to low-saturation
        # pixels, so a white garment may claim its region without stealing
        # the saturated hair strands that hang over it.  A fourth tuple value
        # adds a Lab a* ceiling: cream cloth (a* < 0) must not be confused
        # with pink hair or warm skin (a* > 8), which share its lightness.
        rows = fg.shape[0]
        yy = np.arange(rows, dtype=np.float32)[:, None] / max(rows - 1, 1)
        mx = rgb.max(-1).astype(np.float32)
        mn = rgb.min(-1).astype(np.float32)
        sat_all = (mx - mn) / np.maximum(mx, 1.0)
        for i, m in enumerate(materials):
            span = region_prior.get(m.get("id"))
            if not span:
                continue
            lo, hi = float(span[0]), float(span[1])
            bonus = float(span[2]) if len(span) > 2 else 0.0
            inside = (yy >= lo) & (yy <= hi)
            if bonus < 0:
                gate = sat_all < 0.20
                if len(span) > 3:
                    gate &= lab[..., 1] <= float(span[3])
                weight = np.where(inside & gate, bonus, 0.0)
                weight = np.where(inside, weight, REGION_PENALTY)
                # A claiming band also blocks pale-skin recovery: the cream
                # blouse body touches the neck and would otherwise be grown
                # back into skin across the whole torso.
                owned |= inside
            else:
                weight = np.where(inside, bonus, REGION_PENALTY)
            dist[..., i] += weight
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
              "white_seed", "white_on_hair", "hair_island_recovery",
              "fragment_absorption", "pale_skin", "skin_specks")}

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
                # A two-pixel ring: the left specular is split by lashes, so
                # the 1px ring is diluted by the taupe shadow under it (0.42)
                # while the 2px ring is lash/iris dominated (0.75).  With the
                # 1px ring that comp stayed on the hair ramp (hair refs[0] is
                # #ffffff) and was later absorbed into taupe -- QA issue 5:
                # one iris read as coffee-coloured with no white highlight.
                ring = binary_dilation(comp, iterations=2) & ~comp
                if ring.sum() and ((ring & (seed | dark_ring)).sum()
                                   / ring.sum()) >= 0.55:
                    masks["eye_highlight"] |= comp
                    idx[comp] = white_i[0] if white_i else eye_i[0]
            protected |= np.isin(idx, eye_i) | masks["eye_highlight"]

    skin_like = np.zeros(fg.shape, bool)
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

        # 脸部保护：以双眼为锚的椭圆内，亮白但最近非白材质是皮肤的像素
        # 必须回到皮肤，避免半张脸被白衣阴影染色。
        face = np.zeros_like(fg, dtype=bool)
        near_skin = np.zeros_like(fg, dtype=bool)
        near_eye = np.zeros_like(fg, dtype=bool)
        if eye_i:
            eye_mask = np.isin(idx, eye_i)
            # Stray green specks (shoe laces, foliage) can join the iris
            # material.  A bounding box over *all* iris pixels then spans the
            # whole sprite, making the "face" ellipse cover the torso and
            # turning a cream blouse into skin, so anchor on the two largest
            # iris blobs (the eyes) only.
            lab_e, n_e = label(eye_mask)
            ell = eye_mask
            if n_e:
                sizes_e = np.bincount(lab_e.ravel())
                sizes_e[0] = 0
                keep = np.argsort(sizes_e)[-2:]
                keep = keep[sizes_e[keep] >= 4]
                if keep.size:
                    ell = np.isin(lab_e, keep)
            ys_e, xs_e = np.where(ell)
            if len(ys_e):
                cy = (ys_e.min() + ys_e.max()) / 2.0
                cx = (xs_e.min() + xs_e.max()) / 2.0
                ry = max(24.0, (ys_e.max() - ys_e.min()) * 1.6)
                rx = max(32.0, (xs_e.max() - xs_e.min()) * 0.9 + 20.0)
                yy, xx = np.mgrid[0:fg.shape[0], 0:fg.shape[1]]
                face = (((xx - cx) / rx) ** 2
                        + ((yy - cy) / ry) ** 2) <= 1.0
                near_skin = binary_dilation(
                    np.isin(idx, skin_i), iterations=10)
                near_eye = binary_dilation(eye_mask, iterations=3)
                face_white = (face & near_skin & fg
                              & np.isin(idx, white_i)
                              & ~protected & ~near_eye)
                idx[face_white] = skin_i[0]

    # Ink-fenced white seams are absorbed before the brightness competition;
    # their sampled colour is too warm to survive as white otherwise.
    idx, seam_moved = _absorb_ink_seams(idx, fg, dark, materials, protected)

    if white_i:
        # 已被识别为皮肤或眼部高光的亮部，不允许再被白色种子覆盖；
        # 暖色皮肤（手/颈）即使很亮也不能被白色种子吞掉。
        warm_skin = skin_like & ((rgb[..., 0] - rgb[..., 2]) > 12)
        white_seed = (fg & (sat < 0.10) & (lum > 232)
                      & ~np.isin(idx, skin_i) & ~warm_skin & ~protected)
        before = idx.copy()
        idx[white_seed] = white_i[0]
        masks["white_seed"] = white_seed & (before != idx) | seam_moved

        # Neighbourhood vote: a warm pixel whose 5x5 surround is almost all
        # blouse is antialiased seam, not skin.  A real skin island or hand
        # has a much lower blouse fraction and keeps its material.
        blouse_frac = uniform_filter(
            np.isin(idx, white_i).astype(np.float32), size=5)
        vote = (fg & np.isin(idx, skin_i) & ~protected
                & (blouse_frac >= 0.90))
        if vote.any():
            idx[vote] = white_i[0]
            masks["white_seed"] |= vote

        # White seed runs after the face guard, so bright speculars on the
        # nose/cheek are re-whitened here.  Re-apply the face ellipse once
        # more; eye highlights stay protected.
        if eye_i and skin_i:
            face_white = (face & near_skin & fg & np.isin(idx, white_i)
                          & ~protected & ~near_eye)
            masks["skin_recovery"] |= face_white
            idx[face_white] = skin_i[0]

    # Speculars fully surrounded by hair belong to the hair ramp, not to the
    # blouse.  They stay visually white because hair refs[0] is white.
    hair_i = [i for i, m in enumerate(materials) if m.get("role") == "hair"]
    if white_i and hair_i:
        hair_mask = np.isin(idx, hair_i)
        if hair_mask.any():
            fraction = uniform_filter(hair_mask.astype(np.float32), size=5)
            move = (np.isin(idx, white_i) & fg & (fraction >= 0.62)
                    & ~protected)
            before = idx.copy()
            idx[move] = hair_i[0]
            masks["white_on_hair"] = move & (before != idx)

    # 最后的碎块吸收同样受眼部/暗部保护，不能静默撤销前面的规则。
    out = idx.copy()
    if white_i and skin_i:
        # 下半身两侧的暖白块是手/前臂，不能被白衣吞掉。 手指与袖口/裙摆
        # 在白衣掩码里天然连通，故不能用「是否属于白衣主体」排除；衣内
        # 夹缝改由 _absorb_ink_seams / _absorb_enclosed_skin 按宽度与拓扑处理。
        yy, xx = np.mgrid[0:fg.shape[0], 0:fg.shape[1]]
        ys_fg, xs_fg = np.where(fg)
        y0, y1 = int(ys_fg.min()), int(ys_fg.max())
        x0, x1 = int(xs_fg.min()), int(xs_fg.max())
        lower = yy > y0 + 0.55 * (y1 - y0)
        side = np.abs(xx - (x0 + x1) / 2.0) > 0.10 * (x1 - x0)
        warm = (rgb[..., 0] - rgb[..., 2]) > 14
        hands = (np.isin(out, white_i) & fg & lower & side & warm
                 & (sat > 0.07) & (lum < 252) & ~protected & ~owned)
        masks["skin_recovery"] |= hands
        out[hands] = skin_i[0]
    if white_i and skin_i:
        # 下半身与白衣主体分离、且偏暖的白色碎块（手/前臂）归回皮肤；
        # 袖口等与主体相连的白块不会被拆走。 已知会被声明为白衣的
        # 躯干区（owned）不走这条回填，否则暖白上衣会被整块判成皮肤。
        white_mask = np.isin(out, white_i) & fg
        lab_w, n_w = label(white_mask)
        if n_w:
            sizes = np.bincount(lab_w.ravel())
            sizes[0] = 0
            main_w = int(sizes.argmax())
            ys_fg, _ = np.where(fg)
            y0, y1 = int(ys_fg.min()), int(ys_fg.max())
            warm = (rgb[..., 0] - rgb[..., 2]) > 8
            for k in range(1, n_w + 1):
                if k == main_w:
                    continue
                comp = lab_w == k
                npx = int(comp.sum())
                if npx < 40 or npx > 2000:
                    continue
                if owned is not None and (comp & owned).mean() > 0.5:
                    continue
                ys_c, _ = np.where(comp)
                if ys_c.mean() < y0 + 0.52 * (y1 - y0):
                    continue
                if warm[comp].mean() < 0.55:
                    continue
                out[comp] = skin_i[0]
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

    # A hair-coloured island disconnected from the main hair mass and sitting
    # in the lower body is a skirt/thigh shadow, not hair.  Colour distance
    # alone cannot separate it (hair base and skin mid are ~1.5 Lab apart).
    hair_i = [i for i, m in enumerate(materials) if m.get("role") == "hair"]
    if hair_i:
        hair_mask = np.isin(out, hair_i)
        lab_h, n_h = label(hair_mask)
        if n_h > 1:
            sizes_h = np.bincount(lab_h.ravel())
            sizes_h[0] = 0
            main_h = int(sizes_h.argmax())
            ys_fg, _ = np.where(fg)
            if len(ys_fg):
                y0, y1 = int(ys_fg.min()), int(ys_fg.max())
                for k in range(1, n_h + 1):
                    if k == main_h or sizes_h[k] > 1200:
                        continue
                    comp = lab_h == k
                    ys_c, _ = np.where(comp)
                    if ys_c.mean() < y0 + 0.50 * (y1 - y0):
                        continue
                    ring = binary_dilation(comp, iterations=2) & ~comp & fg
                    vals = out[ring]
                    vals = vals[vals >= 0]
                    if vals.size:
                        new_id = int(np.bincount(vals).argmax())
                        masks["hair_island_recovery"] |= comp
                        out[comp] = new_id

    # Pale skin touching real skin (chest under the chin, inner forearms) is
    # recovered before the fold-core pass so thin slivers are still absorbed.
    anchor = _face_anchor(out, materials)
    face = anchor["face"]
    if face is not None:
        face = binary_dilation(face, iterations=2)
    out, pale_moved = _recover_pale_skin(
        out, fg, rgb, materials, protected, face, owned=owned)
    if pale_moved.any():
        masks["pale_skin"] |= pale_moved

    # Neutral highlights fully enclosed by skin are skin speculars that the
    # brightness competition handed to blouse (and cloth shading tinted green).
    out, speck_moved = _recover_skin_specks(
        out, fg, materials, protected, face)
    if speck_moved.any():
        masks["skin_specks"] |= speck_moved

    # A thin skin sliver whose whole boundary is blouse + ink is a fold core,
    # not skin (v10.2 ①).  Run last so the recovery rules cannot undo it.
    out, sliver_moved = _absorb_enclosed_skin(
        out, fg, dark, materials, protected)
    if sliver_moved.any():
        masks["white_seed"] |= sliver_moved

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


def _split_uniform(idx, materials, fg):
    """把 taupe 连通块按高度拆成 collar/skirt。

    分类器只按颜色聚类，裙子和领子会被并进同一个 taupe 材质；这里按连通块
    的平均高度拆分，使 skirt 的裙褶/裙腰阴影真正生效。
    """
    by_id = {m["id"]: i for i, m in enumerate(materials)}
    ci = by_id.get("collar")
    si = by_id.get("skirt")
    if ci is None or si is None:
        return idx
    ys, _ = np.where(fg)
    if not len(ys):
        return idx
    y0, y1 = int(ys.min()), int(ys.max())
    taupe = (idx == ci) | (idx == si)
    lab, n = label(taupe)
    out = idx.copy()
    for k in range(1, n + 1):
        comp = lab == k
        if comp.sum() < 30:
            continue
        cy, _ = np.where(comp)
        out[comp] = si if cy.mean() > y0 + 0.62 * (y1 - y0) else ci
    return out


def _face_anchor(idx, materials):
    """Locate the face component, eye mask and neck components.

    Iris pixels are a separate material, so the face component never overlaps
    them; probe with a dilated eye mask instead of a strict intersection.
    """
    eye_i = [i for i, m in enumerate(materials) if m.get("role") == "eye"]
    skin_i = [i for i, m in enumerate(materials) if m.get("role") == "skin"]
    anchor = {"face": None, "eyes": None, "box": None, "eye_top": None,
              "neck": []}
    if not eye_i or not skin_i:
        return anchor
    eye_mask = np.isin(idx, eye_i)
    if not eye_mask.any():
        return anchor
    skin_mask = np.isin(idx, skin_i)
    lab_s, n_s = label(skin_mask)
    if n_s == 0:
        return anchor
    eye_probe = binary_dilation(eye_mask, iterations=6)
    face_j, best = 0, 0
    for j in range(1, n_s + 1):
        overlap = int(((lab_s == j) & eye_probe).sum())
        if overlap > best:
            face_j, best = j, overlap
    if not face_j:
        return anchor
    face = lab_s == face_j
    fy, fx = np.where(face)
    ey, _ = np.where(eye_mask)
    anchor.update({
        "face": face,
        "eyes": eye_mask,
        "box": (int(fx.min()), int(fy.min()), int(fx.max()), int(fy.max())),
        "eye_top": int(ey.min()),
    })
    for j in range(1, n_s + 1):
        if j == face_j:
            continue
        comp = lab_s == j
        if comp.sum() < 80:
            continue
        ys_c, xs_c = np.where(comp)
        if ys_c.min() <= fy.min():
            continue
        if xs_c.max() < fx.min() - 10 or xs_c.min() > fx.max() + 10:
            continue
        anchor["neck"].append(comp)
    return anchor


def _keep_large_components(mask, min_px):
    """Drop connected components smaller than min_px (denoise highlight)."""
    if not mask.any():
        return mask
    lab, n = label(mask)
    if n == 0:
        return mask
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    keep_ids = np.where(sizes >= max(int(min_px), 1))[0]
    keep_ids = keep_ids[keep_ids > 0]
    return np.isin(lab, keep_ids)


def render_spec(rgb, fg, pal, materials, tier="half", return_debug=False,
                drawing_config=None, body=None, detect_scale=1.0,
                region_prior=None):
    """按 spec.materials 上色：颜色来自各材质 refs，全部吸附到 16 色板。

    ``detect_scale`` converts the 640x400 classification area limits to the
    actual detection resolution (1.0 keeps the legacy 640x400 behaviour).
    Callers rendering above the reference size must pass the real factor,
    otherwise small parts are absorbed and large parts swap materials.
    """
    pal = np.asarray(pal, np.uint8)
    ids = _ids(pal)
    pal_hue, pal_sat, _ = _hsv(pal.astype(np.float32) / 255.0)

    def snap(color):
        c = np.asarray(color, np.float32)
        d = ((pal.astype(np.float32) - c) ** 2).sum(1)
        # Hue guard: a saturated reference must not snap to a slot of another
        # hue.  Without it the dark teal iris ref #1f5f5a lands on taupe
        # (74,63,54) (dH 148 deg, 0.7% closer in RGB) and the dark gold bow ref
        # #a87a1e lands on skin brown -- both read as a colour swap on screen.
        hue, sat, _ = _hsv((c / 255.0)[None, None, :])
        hue, sat = float(hue[0, 0]), float(sat[0, 0])
        if sat >= 0.20:
            dh = np.abs(pal_hue - hue)
            dh = np.minimum(dh, 360.0 - dh)
            same_hue = (dh <= 15.0) & (pal_sat >= 0.15)
            if same_hue.any():
                d = np.where(same_hue, d, np.inf)
        return pal[int(np.argmin(d))]

    def nearest_of(mask, refs):
        cand = np.array([snap(r) for r in refs], np.float32)
        sub = rgb[mask].astype(np.float32)
        d = ((sub[:, None, :] - cand[None, :, :]) ** 2).sum(-1)
        return cand[d.argmin(1)].astype(np.uint8)

    if return_debug:
        idx, debug = classify_materials(
            rgb, fg, materials, tier=tier, return_debug=True,
            scale=detect_scale, region_prior=region_prior)
    else:
        idx = classify_materials(rgb, fg, materials, tier=tier,
                                 scale=detect_scale,
                                 region_prior=region_prior)
    idx = _split_uniform(idx, materials, fg)
    if return_debug:
        debug["material_idx"] = idx.copy()
    lum = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1]
           + 0.114 * rgb[..., 2]) / 255.0
    light = shading.light_vector(
        (drawing_config or {}).get("light", "upper-left"))
    scale = max(1.0, fg.shape[1] / 257.0)
    ink = shading.ink_mask(lum, 0.22, 2)
    anchor = _face_anchor(idx, materials)
    YY = np.mgrid[0:fg.shape[0], 0:fg.shape[1]][0]

    # 五类布料层只改变层内着色，不回写材质分类。
    cloth = drawing.build_cloth_layers(
        rgb, fg, idx, materials, drawing_config, body=body)

    fills = np.zeros(rgb.shape, np.uint8)
    hair_ids = [i for i, m in enumerate(materials) if m.get("role") == "hair"]
    hair_mask_all = (np.isin(idx, hair_ids) if hair_ids
                     else np.zeros_like(fg))
    for i, m in enumerate(materials):
        mask = idx == i
        if not mask.any():
            continue
        role = m.get("role", "flat")
        refs = [_hex_rgb(s) for s in m.get("refs", ["#ffffff"])]
        base = snap(refs[0])
        if role in ("white", "cloth"):
            # Volume shading for cloth/white lives in build_cloth_layers so
            # that config folds/occlusions and the silhouette band share one
            # tone map.
            fills[mask] = base
        elif role == "hair":
            tones = [snap(r) for r in refs]
            hi_t = tones[0]
            base_t = tones[1] if len(tones) > 1 else tones[0]
            mid_t = tones[2] if len(tones) > 2 else tones[-1]
            deep_t = tones[3] if len(tones) > 3 else tones[-1]
            fills[mask] = base_t
            mid, deep, core = shading.directional_bands(
                mask, light, (0.75, 0.30, 0.12), min_px=8)
            fills[mid] = mid_t
            fills[deep] = deep_t
            if len(tones) > 4:
                fills[core] = tones[4]
            # Highlight = the artist's painted speculars: the brightest source
            # pixels inside the head area (crown to eye line).  The old model
            # drew hard-coded strokes (_hair_streaks) that floated over the
            # hair as jarring diagonal bars; reading luminance places the
            # highlight where the art actually has it and follows the locks.
            if anchor["box"] is not None:
                bx0, by0, bx1, by1 = anchor["box"]
                head_limit = int(by0 + 0.70 * (by1 - by0 + 1))
            else:
                ys_h, _ = np.where(mask)
                head_limit = int(ys_h.min()
                                 + 0.40 * (ys_h.max() - ys_h.min() + 1))
            head_area = mask & (YY <= head_limit) & ~ink
            bright = head_area & (lum >= 0.74)
            bright = binary_opening(bright, structure=np.ones((2, 2), bool))
            bright = _keep_large_components(bright, 10)
            fills[bright] = hi_t
        elif role == "skin":
            # Skin and clothes share the same upper-left body light.  The face
            # uses a narrow spherical crescent; neck/limbs use cylinder fields.
            tones = [snap(r) for r in refs]
            base_t = tones[0]
            mid_t = tones[1] if len(tones) > 1 else tones[-1]
            deep_t = tones[2] if len(tones) > 2 else tones[-1]
            fills[mask] = base_t
            mid = np.zeros_like(mask)
            deep = np.zeros_like(mask)
            if hair_mask_all.any():
                head_zone = mask
                if anchor["face"] is not None:
                    reach = int(round(0.20 * fg.shape[1]))
                    head_zone = binary_dilation(
                        anchor["face"], iterations=reach) & mask
                    for neck in anchor["neck"]:
                        head_zone |= neck & mask
                else:
                    ys_fg, _ = np.where(fg)
                    if len(ys_fg):
                        head_zone = mask & (
                            YY <= ys_fg.min()
                            + 0.60 * (ys_fg.max() - ys_fg.min()))
                cast = shading.cast_shadow(
                    hair_mask_all, head_zone, light, depth=4.0 * scale)
                if anchor["eyes"] is not None:
                    cast &= ~binary_dilation(anchor["eyes"], iterations=8)
                mid |= cast
            cloth_ids = [j for j, mat in enumerate(materials)
                         if mat.get("role") in ("white", "cloth")]
            cloth_mask = (np.isin(idx, cloth_ids) if cloth_ids
                          else np.zeros_like(mask))
            ys_fg, xs_fg = np.where(fg)
            fg_mid_x = (float(xs_fg.min()) + float(xs_fg.max())) / 2.0
            leg_y = float(ys_fg.min()) + 0.72 * (
                float(ys_fg.max()) - float(ys_fg.min()))
            lab_s, n_s = label(mask)
            for j in range(1, n_s + 1):
                comp = lab_s == j
                if comp.sum() < 50:
                    continue
                ys_c, xs_c = np.where(comp)
                is_face = (anchor["face"] is not None and
                           (comp & anchor["face"]).sum() > 0.5 * comp.sum())
                is_neck = any((comp & neck).sum() > 0.5 * comp.sum()
                              for neck in anchor["neck"])
                if is_face:
                    face_cx = 0.5 * (float(xs_c.min()) + float(xs_c.max()))
                    face_cy = 0.5 * (float(ys_c.min()) + float(ys_c.max()))
                    face_rx = max(1.0, 0.5 * (xs_c.max() - xs_c.min() + 1))
                    face_ry = max(1.0, 0.5 * (ys_c.max() - ys_c.min() + 1))
                    face_field = shading.ellipsoid_field(
                        comp, face_cx, face_cy, face_rx, face_ry, light,
                        terminator=0.38)
                    band, _, _ = shading.field_bands(
                        face_field, comp, thresholds=(0.30,), min_px=12)
                    if anchor["eyes"] is not None:
                        band &= ~binary_dilation(anchor["eyes"], iterations=8)
                    deep_band = np.zeros_like(comp)
                else:
                    is_leg = float(ys_c.min()) >= leg_y
                    deep_threshold = (0.68 if is_leg and
                                      float(xs_c.mean()) > fg_mid_x else 0.86)
                    band, deep_band, _ = shading.continuous_bands(
                        comp, light, thresholds=(0.38, deep_threshold),
                        min_px=12)
                    if cloth_mask.any():
                        # Sleeve/skirt hems cast onto the receiving limb and
                        # merge with that limb's own cylindrical back-light.
                        band |= shading.cast_shadow(
                            cloth_mask, comp, light, depth=3.0 * scale)
                    if is_neck:
                        depth = int(round(4.0 * scale))
                        band |= comp & (YY <= int(ys_c.min()) + depth)
                        if anchor["face"] is not None:
                            band |= shading.cast_shadow(
                                anchor["face"], comp, light, depth=3.0 * scale)
                mid |= band
                deep |= deep_band
            mid &= mask
            deep &= mask & mid
            combined = binary_closing(mid | deep, structure=np.ones((2, 2), bool))
            lab_m, n_m = label(combined)
            keep = np.zeros_like(combined)
            for j in range(1, n_m + 1):
                comp = lab_m == j
                if comp.sum() >= 20:
                    keep |= comp
            fills[keep & mid] = mid_t
            fills[keep & deep] = deep_t
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
