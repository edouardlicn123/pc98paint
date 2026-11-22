# -*- coding: utf-8 -*-
"""PC-98 游乐园场景（galgame 背景路线）：高清源 → pc98core 管线 → 640×400。

流程（算法主体见 tools/lib/pc98core.py，AGENTS.md 有索引）：
1. 高清源裁掉水印、收敛 16:10，两级面积缩放（1280×800 → 640×400）；
2. pc98core.line_layer：2× 上提线稿，2×2 取最大下采样合成 1px 线；
3. pc98core.index_colors：96 原色 + 96 伙伴色，平坦区铺方向性交错，
   线稿色归并 16 色。

输出：
    pc98/pc98_park_gal_640x400.png   主图（256 索引色内）
"""
from pathlib import Path
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))

import pc98core

SRC = ROOT / "_work" / "pc98_src" / "1990s_Japanese_visual_novel_ba_2026-11-21T11-11-11.png"
OUT_DIR = ROOT / "output"          # 产出统一写 output/（见 AGENTS.md）
NAME = "park_gal"


def load(src):
    """本项目源图专用裁切：去水印带 → 16:10 → 2× 中间分辨率。"""
    img = Image.open(src).convert("RGB")
    img = img.crop((0, 0, img.width, img.height - 48))   # 去掉右下角水印带
    w, h = img.size
    img = img.crop((0, 0, w, min(h, int(w / 1.6))))      # 收敛到 16:10
    return img.resize((1280, 800), Image.BOX), (640, 400)


def main():
    mid, target = load(SRC)
    color = mid.resize(target, Image.BOX)
    lmask, lcolor = pc98core.line_layer(mid, target)
    out, stats = pc98core.index_colors(color, lmask, lcolor)

    res = Image.fromarray(out, "RGB")
    main_path = OUT_DIR / f"pc98_{NAME}_640x400.png"
    res.save(main_path)

    print("colors:", stats["colors"], "lines:", stats["lines_pct"], "%",
          "partner:", stats["partner_pct"], "%")
    print("saved:", main_path)


if __name__ == "__main__":
    main()
