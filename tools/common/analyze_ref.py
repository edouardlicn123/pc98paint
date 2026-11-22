# -*- coding: utf-8 -*-
"""参考图用色分析器。

输出：色数、17 吸附率、黑线占比、边界交错率、色相族、明度阶梯、
以及与本项目 16 色槽位系统的覆盖率。

用法：
    python analyze_ref.py IMAGE [--json OUT] [--top 40]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

import palette98 as P


def _runs(mask, axis=1):
    counts = {}
    for row in np.moveaxis(mask, axis, 0):
        c = 0
        for v in row:
            if v:
                c += 1
            elif c:
                counts[c] = counts.get(c, 0) + 1
                c = 0
        if c:
            counts[c] = counts.get(c, 0) + 1
    return counts


def _hue_families(items, threshold=15.0):
    """按色相排序后按空隙切族，避免逐点聚类把整圈色相连成一片。items: [(h,s,v,count)]"""
    colored = sorted(
        [it for it in items if it[1] >= 0.3 and it[2] >= 0.15],
        key=lambda x: x[0],
    )
    if not colored:
        return []

    n = len(colored)
    gaps = [((colored[(i + 1) % n][0] - colored[i][0]) % 360) for i in range(n)]
    start = int(np.argmax(gaps))
    ordered = colored[start:] + colored[:start]

    groups, cur = [], [ordered[0]]
    for prev, it in zip(ordered, ordered[1:]):
        if (it[0] - prev[0]) % 360 > threshold:
            groups.append(cur)
            cur = [it]
        else:
            cur.append(it)
    groups.append(cur)

    out = []
    for g in groups:
        hue = float(np.average([x[0] for x in g], weights=[x[3] for x in g]) % 360)
        vals = sorted({round(x[2], 2) for x in g}, reverse=True)
        merged = []
        for v in vals:
            if not merged or abs(v - merged[-1]) > 0.03:
                merged.append(v)
        out.append({
            "hue": round(hue, 1),
            "pixels": int(sum(x[3] for x in g)),
            "values": merged,
            "colors": [
                {"h": round(x[0], 1), "s": round(x[1], 2), "v": round(x[2], 2), "count": int(x[3])}
                for x in sorted(g, key=lambda x: -x[3])
            ],
        })
    return sorted(out, key=lambda x: -x["pixels"])


def analyze(path, top=40, skip_transparent=True):
    im = Image.open(path)
    rgba = np.array(im.convert("RGBA"))
    rgb = rgba[..., :3].astype(np.uint8)
    if skip_transparent and rgba[..., 3].min() < 255:
        fg = rgba[..., 3] > 0
    else:
        fg = np.ones(rgb.shape[:2], bool)

    flat = rgb[fg]
    cols, cnt = np.unique(flat, axis=0, return_counts=True)
    order = np.argsort(-cnt)
    cols, cnt = cols[order], cnt[order]
    total = int(cnt.sum())

    on_grid_col = sum(1 for c in cols if (c.astype(int) % 17).max() == 0)
    on_grid_px = int(sum(int(n) for c, n in zip(cols, cnt) if (c.astype(int) % 17).max() == 0))
    black = int(((cols == 0).all(1) * cnt).sum())
    white = int(((cols == 255).all(1) * cnt).sum())

    ids = np.zeros(rgb.shape[:2], np.int32)
    for i, c in enumerate(cols):
        ids[(rgb == c).all(-1)] = i + 1
    dr = (ids[:, 1:] != ids[:, :-1]).mean()
    dd = (ids[1:, :] != ids[:-1, :]).mean()
    boundary = float((dr + dd) / 2)

    runs = _runs((rgb == 0).all(-1) & fg, 1)

    candidates = [(n, P.snap17(c), "core") for n, c in P.CORE.items()]
    candidates += [(n, P.snap17(c), "flex") for n, c in P.FLEX.items()]
    lab_cand = P.rgb_to_lab(np.array([c for _, c, _ in candidates], float))

    items = []
    matched_px = 0
    unmatched = []
    for c, n in zip(cols, cnt):
        h, s, v = P.rgb_to_hsv(c)
        lab = P.rgb_to_lab(c.astype(float))
        d = np.linalg.norm(lab_cand - lab, axis=1)
        k = int(np.argmin(d))
        de = float(d[k])
        slot = candidates[k][0] if de <= 12 else ""
        if de <= 12:
            matched_px += int(n)
        else:
            unmatched.append({"rgb": [int(x) for x in c], "count": int(n), "de": round(de, 1)})
        items.append({
            "rgb": [int(x) for x in c],
            "count": int(n),
            "pct": round(100.0 * n / total, 2),
            "h": round(float(h), 1),
            "s": round(float(s), 2),
            "v": round(float(v), 2),
            "slot": slot,
            "de": round(de, 1),
        })

    return {
        "path": str(path),
        "size": [im.width, im.height],
        "unique_colors": int(len(cols)),
        "on_grid_color_pct": round(100.0 * on_grid_col / len(cols), 1),
        "on_grid_pixel_pct": round(100.0 * on_grid_px / total, 2),
        "black_pct": round(100.0 * black / total, 2),
        "white_pct": round(100.0 * white / total, 2),
        "boundary_pct": round(100.0 * boundary, 2),
        "black_runs": {str(k): v for k, v in sorted(runs.items())},
        "colors": items[:top],
        "hue_families": _hue_families(
            [(it["h"], it["s"], it["v"], it["count"]) for it in items]
        ),
        "slot_coverage": {
            "matched_pixel_pct": round(100.0 * matched_px / total, 2),
            "matched_colors": len(cols) - len(unmatched),
            "total_colors": int(len(cols)),
            "unmatched": unmatched[:20],
        },
    }


def print_report(r):
    print(f"== {Path(r['path']).name} ==")
    print(f"尺寸 {r['size'][0]}x{r['size'][1]}  色数 {r['unique_colors']}  "
          f"17吸附 {r['on_grid_color_pct']}%色 / {r['on_grid_pixel_pct']}%像素")
    print(f"黑 {r['black_pct']}%  白 {r['white_pct']}%  边界交错 {r['boundary_pct']}%")
    runs = r["black_runs"]
    print("黑线连续段", {k: runs[k] for k in sorted(runs, key=lambda x: int(x))[:4]})
    print("-- 主色 --")
    for it in r["colors"][:18]:
        slot = it["slot"] or f"?dE{it['de']}"
        print(f"  {str(tuple(it['rgb'])):18s} {it['pct']:5.1f}%  "
              f"H{it['h']:5.1f} S{it['s']:.2f} V{it['v']:.2f}  {slot}")
    print("-- 色相族 --")
    for f in r["hue_families"][:8]:
        print(f"  H{f['hue']:5.1f}  {f['pixels']:6d}px  V={f['values']}")
    cov = r["slot_coverage"]
    print(f"-- 槽位覆盖 {cov['matched_colors']}/{cov['total_colors']} 色，"
          f"{cov['matched_pixel_pct']}% 像素 --")
    if cov["unmatched"]:
        print("  未匹配:", [u["rgb"] for u in cov["unmatched"][:8]])


def main():
    ap = argparse.ArgumentParser(description="参考图用色分析")
    ap.add_argument("image")
    ap.add_argument("--json", default="")
    ap.add_argument("--top", type=int, default=40)
    args = ap.parse_args()

    r = analyze(args.image, args.top)
    print_report(r)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        print("saved", args.json)


if __name__ == "__main__":
    main()
