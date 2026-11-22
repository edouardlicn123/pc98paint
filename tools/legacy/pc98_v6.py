# -*- coding: utf-8 -*-
"""PC-98 管线 v6：高分辨率源 → 机器分辨率，先保线再减色。

流程：
1. 高清源裁成目标比例（场景 16:10，立绘 4:5），两级面积缩放；
2. 在 2× 上提线稿，按 2×2 取最大下采样到 1×，单独合成 1px 线；
3. 96 个原色 + 96 个同明度异色相伙伴 = 192 色；
4. 只在"平坦区"铺 1px 交错（密度 35%），细节区不抖，避免糊。

算法主体已抽至 _work/pc98core.py（见 AGENTS.md），本文件只保留
源图裁切与运行入口。模块级执行已加 __main__ 保护，可安全 import。
"""
from pathlib import Path

import numpy as np
from PIL import Image

import pc98core

ROOT = Path(__file__).resolve().parents[2]


def load(src, mode):
    img = Image.open(src).convert("RGB")
    if mode == "scene":
        img = img.crop((0, 0, img.width - 320, img.height - 40))  # 2240×1400，去掉右下角水印
        target = (640, 400)
    else:
        img = img.crop((0, 0, img.width, img.height * 15 // 16))  # 4:5，去掉底部水印
        target = (320, 400)
    mid = img.resize((target[0] * 2, target[1] * 2), Image.BOX)
    return mid, target


def run(name, src, mode, n_base=96, density=0.35):
    mid, target = load(src, mode)
    color = mid.resize(target, Image.BOX)
    lmask, lcolor = pc98core.line_layer(mid, target)

    out, stats = pc98core.index_colors(np.array(color), lmask, lcolor,
                                       n_base=n_base, density=density)
    res = Image.fromarray(out, "RGB")
    if mode == "tachie":
        canvas = Image.new("RGB", (640, 400), (255, 255, 255))
        canvas.paste(res, (160, 0))
        res = canvas
    out_path = ROOT / "output" / f"pc98_v6_{name}_640x400.png"   # 产出统一写 output/
    res.save(out_path)

    if mode == "tachie":
        box = (180, 20, 460, 260)
        zoom = res.crop(box).resize(((box[2] - box[0]) * 3, (box[3] - box[1]) * 3), Image.NEAREST)
        zoom.save(ROOT / "pc98" / f"pc98_v6_{name}_zoom.png")

    print(name, "colors", stats["colors"], "lines", stats["lines_pct"], "%",
          "partner", stats["partner_pct"], "%")


if __name__ == "__main__":
    run("tachie", ROOT / "_work" / "pc98_src" / "tachie_90s_hi.jpg", "tachie")
    run("scene", ROOT / "_work" / "pc98_src" / "scene_corridor_hi.jpg", "scene")
