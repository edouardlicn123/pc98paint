# -*- coding: utf-8 -*-
"""PC-98 教室场景（galgame 背景路线）：高清源 → pc98core 管线 → 640×400。

流程与 pc98_scene_park_gal.py 一致（算法主体见 tools/lib/pc98core.py）：
1. 高清源裁掉右下角水印带、收敛 16:10，两级面积缩放（1280×800 → 640×400）；
2. pc98core.line_layer：2× 上提线稿，2×2 取最大下采样合成 1px 线；
3. pc98core.index_colors：96 原色 + 96 伙伴色，平坦区铺方向性交错，
   线稿色归并 16 色。

用法（项目根目录）：
    python tools/scene/pc98_scene_classroom_gal.py --src _work/pc98_src/xxx.jpg --name classroom_xxx

输出（统一写 output/，不生成 zoom，见 AGENTS.md）：
    output/pc98_<名称>_640x400.png   主图（256 索引色内）
"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))

from PIL import Image, ImageEnhance, ImageFilter

import pc98core

OUT_DIR = ROOT / "output"

# 已验证的雾感夕阳源图参数；可用同名命令行选项覆盖。
SATURATION = 1.22
CONTRAST = 1.16
CROP_SCALE = 0.9


def load(src, crop_scale, saturation, contrast):
    """源图预处理：裁切 → 16:10 → 提饱和/对比 → 中间分辨率 → 中值降噪。

    降噪必须放在 1280×800 之后：源图尺度的 3px 中值会连 1px 线稿一起磨掉；
    中间尺度的 3px 中值约等于源图 3.6px，正好清掉照片颗粒，
    让 pc98core 的 flat 判定（detail < 5.0）能正常认出桌面、墙面这些大片区域。
    """
    with Image.open(src) as source:
        img = source.convert("RGB")
    # 等比例裁去右侧与底部水印带；crop_scale=1 时保留完整源图。
    img = img.crop((0, 0, int(img.width * crop_scale), int(img.height * crop_scale)))
    w, h = img.size
    img = img.crop((0, 0, w, min(h, int(w / 1.6))))
    img = ImageEnhance.Color(img).enhance(saturation)
    img = ImageEnhance.Contrast(img).enhance(contrast)
    mid = img.resize((1280, 800), Image.BOX)
    return mid.filter(ImageFilter.MedianFilter(3)), (640, 400)


def main(argv=None):
    parser = argparse.ArgumentParser(description="高清教室源图 → PC-98 640×400 主图（不生成 zoom）")
    parser.add_argument("--src", type=Path, required=True, help="高清源图路径")
    parser.add_argument("--name", required=True, help="输出名称，不含 pc98_ 前缀和分辨率后缀")
    parser.add_argument("--crop-scale", type=float, default=CROP_SCALE,
                        help="右侧和底部的等比例保留量，1 表示不裁切（默认 %(default)s）")
    parser.add_argument("--saturation", type=float, default=SATURATION,
                        help="源图饱和度倍率（默认 %(default)s）")
    parser.add_argument("--contrast", type=float, default=CONTRAST,
                        help="源图对比度倍率（默认 %(default)s）")
    args = parser.parse_args(argv)
    if not 0 < args.crop_scale <= 1:
        parser.error("--crop-scale 必须大于 0 且不超过 1")
    if args.saturation <= 0 or args.contrast <= 0:
        parser.error("--saturation 和 --contrast 必须大于 0")

    mid, target = load(args.src, args.crop_scale, args.saturation, args.contrast)
    color = mid.resize(target, Image.BOX)
    lmask, lcolor = pc98core.line_layer(mid, target)
    out, stats = pc98core.index_colors(color, lmask, lcolor)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    res = Image.fromarray(out, "RGB")
    main_path = OUT_DIR / f"pc98_{args.name}_640x400.png"
    res.save(main_path)

    print("colors:", stats["colors"], "lines:", stats["lines_pct"], "%",
          "partner:", stats["partner_pct"], "%")
    print("saved:", main_path)


if __name__ == "__main__":
    main()
