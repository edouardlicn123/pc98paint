# -*- coding: utf-8 -*-
"""PC-98 游乐园场景生成器：按《02_场景的做法》流程的程序化实现。

与文档步骤的对应关系（docs/02_场景的做法.md）：
- 构图与透视：地平线 y=248（胸口机位），沙径梯形向消失点收束；
- 方向性渐变场：天空 4 档密度带、帐篷曲面的明暗衰减；
- 等方材质场：草地双向绿点、沙径细密噪点、树冠三层绿斑；
- 结构线：摩天轮钢架、灯杆用亮/深细线，不做交错；
- 实色锚点：灯管核心、旗面、气球高光；
- 景深衰减：远景（摩天轮、树带）降饱和、向天色靠拢、细节变粗；
- 留位：画面中下部沙径区低细节低对比，供立绘站位。

规格：640×400、256 索引色（PEGC），量化关闭抖动。
输出：
    pc98/pc98_park_scene_640x400.png      主图
"""
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "pc98"
OUT.mkdir(exist_ok=True)

W, H = 640, 400
HORIZON = 248

rng = np.random.default_rng(42)
img = np.zeros((H, W, 3), dtype=np.float64)


# ---------- 基础工具 ----------
def mix(c1, c2, t):
    return tuple(c1[i] * (1 - t) + c2[i] * t for i in range(3))


def px(x, y, c):
    if 0 <= y < H and 0 <= x < W:
        img[y, x] = c


def bayer(x, y):
    # 8x8 Bayer 阈值，用于密度可控的交错
    b = np.array([[0, 32, 8, 40, 2, 34, 10, 42],
                  [48, 16, 56, 24, 50, 18, 58, 26],
                  [12, 44, 4, 36, 14, 46, 6, 38],
                  [60, 28, 52, 20, 62, 30, 54, 22],
                  [3, 35, 11, 43, 1, 33, 9, 41],
                  [51, 19, 59, 27, 49, 17, 57, 25],
                  [15, 47, 7, 39, 13, 45, 5, 37],
                  [63, 31, 55, 23, 61, 29, 53, 21]])
    return (b[y % 8, x % 8] + 0.5) / 64.0


def rect(x0, y0, x1, y1, c):
    for y in range(max(0, y0), min(H, y1 + 1)):
        for x in range(max(0, x0), min(W, x1 + 1)):
            px(x, y, c)


def fill_disc(cx, cy, r, c):
    r2 = r * r
    for y in range(int(cy - r), int(cy + r) + 1):
        for x in range(int(cx - r), int(cx + r) + 1):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r2:
                px(x, y, c)


def ellipse_soft(cx, cy, rx, ry, c):
    # 实色椭圆 + 2px 交错软化边缘（投影做法：边缘用交错衰减）
    for y in range(int(cy - ry) - 2, int(cy + ry) + 3):
        for x in range(int(cx - rx) - 2, int(cx + rx) + 3):
            d = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
            if d <= 0.86:
                px(x, y, c)
            elif d <= 1.12:
                if bayer(x, y) < 0.5:
                    px(x, y, c)


def line(x0, y0, x1, y1, c):
    # Bresenham 1px 结构线
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx - dy
    while True:
        px(x0, y0, c)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy


# ---------- 调色板（场所决定饱和度：游乐园 = 高饱和、低局部对比） ----------
SKY_DEEP = (58, 104, 190)
SKY_MID = (108, 152, 214)
SKY_LIGHT = (168, 200, 232)
SKY_PALE = (214, 228, 240)
CLOUD = (244, 248, 250)
CLOUD_SHADE = (198, 214, 232)

GRASS = (98, 162, 86)
GRASS_LIGHT = (124, 184, 98)
GRASS_DARK = (74, 130, 74)
SHADOW = (78, 112, 96)          # 投影偏冷（蓝绿）

PATH = (214, 190, 144)
PATH_DARK = (186, 156, 112)

TREE_FAR = (132, 180, 159)      # 远树带：向天色靠拢（饱和衰减）

TENT_A = (232, 124, 170)        # 粉紫帐篷
TENT_B = (246, 178, 200)
TENT_SHADE = (168, 84, 134)     # 背光面换色相（偏紫）
TENT_TRIM = (120, 60, 110)
FLAG_RED = (212, 64, 56)

RIM = mix((240, 236, 226), SKY_LIGHT, 0.20)   # 摩天轮结构线：远景提亮混天色
LEG = mix((108, 104, 124), SKY_LIGHT, 0.15)
CABIN_COLORS = [(214, 70, 60), (238, 192, 66), (62, 160, 158), (222, 130, 70)]

STALL_RED = (212, 64, 56)
STALL_YEL = (244, 200, 72)
WOOD = (128, 92, 60)
WOOD_DARK = (96, 66, 44)

TRUNK = (120, 84, 56)
TRUNK_DARK = (88, 60, 40)
TREE_D = (48, 104, 60)
TREE_M = (80, 152, 76)
TREE_L = (144, 200, 92)

LAMP_CORE = (250, 244, 214)     # 灯管实色锚点
LAMP_GLOW = (240, 226, 180)
POLE = (64, 68, 88)

CROWD = [(70, 70, 96), (96, 64, 72), (64, 88, 72), (110, 84, 60)]
BALLOON = [(214, 70, 60), (238, 192, 66), (62, 160, 158), (232, 124, 170)]


# ---------- 1-2. 天空：方向性渐变场（4 档密度带，非连续渐变） ----------
SKY_STOPS = [SKY_DEEP, SKY_MID, SKY_LIGHT, SKY_PALE]
for y in range(0, HORIZON):
    t = y / HORIZON * (len(SKY_STOPS) - 1)
    i = min(int(t), len(SKY_STOPS) - 2)
    f = t - i
    for x in range(W):
        px(x, y, SKY_STOPS[i + 1] if bayer(x, y) < f else SKY_STOPS[i])


# ---------- 3. 云：平色块 + 底部 1-2px 交错影 ----------
def cloud(cx, cy, s):
    for dx, dy, r in [(-s, 3, s * 0.7), (0, 0, s), (s, 3, s * 0.7), (s // 2, -s // 3, s * 0.6)]:
        fill_disc(cx + dx, cy + dy + 3, r, CLOUD_SHADE)   # 底影先铺
    for dx, dy, r in [(-s, 3, s * 0.7), (0, 0, s), (s, 3, s * 0.7), (s // 2, -s // 3, s * 0.6)]:
        fill_disc(cx + dx, cy + dy, r, CLOUD)             # 亮体上移，露出下缘影


cloud(340, 58, 16)
cloud(520, 44, 12)
cloud(600, 108, 9)


# ---------- 4. 远景树带：细节收敛为一条起伏剪影 ----------
for x in range(W):
    y0 = 236 + int(4 * np.sin(x * 0.05) + 2.5 * np.sin(x * 0.13 + 1.2))
    for y in range(y0, HORIZON):
        px(x, y, TREE_FAR)


# ---------- 5. 地面：等方材质场 ----------
for y in range(HORIZON, H):
    for x in range(W):
        base = GRASS_LIGHT if bayer(x, y) < 0.25 else GRASS
        px(x, y, base)
# 草地暗斑（等方场密度缓变）
ellipse_soft(90, 340, 70, 14, GRASS_DARK)
ellipse_soft(540, 356, 80, 16, GRASS_DARK)
ellipse_soft(400, 290, 55, 9, GRASS_DARK)

# ---------- 6. 沙径：一点透视梯形 + 细密等方噪点（立绘留位区，低细节） ----------
for y in range(HORIZON, H):
    t = (y - HORIZON) / (H - HORIZON)
    x0 = int(306 + (210 - 306) * t)
    x1 = int(334 + (430 - 334) * t)
    for x in range(x0, x1 + 1):
        c = PATH_DARK if rng.random() < 0.10 else PATH
        px(x, y, c)
    # 径缘交错：与草地互相咬合 1-2px
    for k in range(2):
        if bayer(x0 - 1 - k, y) < 0.5:
            px(x0 - 1 - k, y, PATH)
        if bayer(x1 + 1 + k, y) < 0.5:
            px(x1 + 1 + k, y, PATH)


# ---------- 7. 投影（先于物件：光源左上，影落右下，偏冷） ----------
ellipse_soft(150, 322, 48, 8, SHADOW)     # 摩天轮基座
ellipse_soft(520, 270, 92, 12, SHADOW)    # 帐篷
ellipse_soft(112, 296, 42, 7, SHADOW)     # 摊位 1
ellipse_soft(232, 282, 34, 6, SHADOW)     # 摊位 2
ellipse_soft(44, 318, 52, 9, SHADOW)      # 左树
ellipse_soft(604, 336, 55, 10, SHADOW)    # 右树


# ---------- 8. 摩天轮：结构线（亮色细线，不做交错）+ 远景衰减 ----------
WCX, WCY, WR = 150, 160, 92
# 轮缘双圈
for rr in (WR, WR - 5):
    steps = int(2 * np.pi * rr * 2.2)
    for s in range(steps):
        a = s / steps * 2 * np.pi
        px(int(WCX + rr * np.cos(a)), int(WCY + rr * np.sin(a)), RIM)
# 辐条 12 根
for k in range(12):
    a = k * np.pi / 6
    line(WCX, WCY, int(WCX + WR * np.cos(a)), int(WCY + WR * np.sin(a)), RIM)
# 轿厢：小色块，挂于轮缘
for k in range(12):
    a = k * np.pi / 6 + np.pi / 12
    cx_, cy_ = int(WCX + (WR + 6) * np.cos(a)), int(WCY + (WR + 6) * np.sin(a))
    line(int(WCX + WR * np.cos(a)), int(WCY + WR * np.sin(a)), cx_, cy_, RIM)
    c = mix(CABIN_COLORS[k % 4], SKY_LIGHT, 0.18)   # 远景饱和衰减
    rect(cx_ - 3, cy_, cx_ + 3, cy_ + 4, c)
    px(cx_ - 3, cy_, mix(c, (255, 255, 255), 0.4))  # 1px 亮缘
# 轮心与支架（A 字腿距加宽，双横撑）
fill_disc(WCX, WCY, 5, LEG)
line(WCX, WCY, 102, 318, LEG)
line(WCX, WCY, 198, 318, LEG)
line(116, 268, 184, 268, LEG)
line(106, 300, 194, 300, LEG)
rect(92, 316, 208, 319, WOOD_DARK)


# ---------- 9. 大帐篷：方向性褶皱带 + 装饰纹 + 背光面 ----------
TX, APEX, WALL_TOP, WALL_BOT, TR = 460, 92, 170, 254, 110
# 锥顶：条纹按辐角收束于顶点（gore 条纹）
for y in range(APEX, WALL_TOP):
    half = 8 + (y - APEX) * (TR - 8) / (WALL_TOP - APEX)
    for x in range(int(TX - half), int(TX + half) + 1):
        dx = x - TX
        if abs(dx) > half:
            continue
        theta = np.arctan2(y - APEX, dx)
        gore = int(theta / np.pi * 12) % 2
        c = TENT_B if gore else TENT_A
        if dx > half * 0.45:                     # 背光面：换色相偏紫
            c = mix(c, TENT_SHADE, 0.5 if bayer(x, y) < 0.7 else 0.25)
        px(x, y, c)
# 帐篷墙：竖直条纹（12 幅整除，与锥顶辐角对齐）
for x in range(TX - TR, TX + TR + 1):
    gore = ((x - (TX - TR)) * 12 // (2 * TR + 1)) % 2
    for y in range(WALL_TOP, WALL_BOT + 1):
        c = mix(TENT_B, TENT_SHADE, 0.18) if gore else mix(TENT_A, TENT_SHADE, 0.12)
        if x > TX + 34:
            c = mix(c, TENT_SHADE, 0.5 if bayer(x, y) < 0.7 else 0.25)
        px(x, y, c)
# 锥墙交界装饰线 + 条纹分界点（装饰纹样，非明暗）
for x in range(TX - TR, TX + TR + 1):
    px(x, WALL_TOP, TENT_TRIM)
for k in range(13):
    xb = TX - TR + k * (2 * TR) // 12
    for dy in range(-2, 3):
        if abs(dy) <= 2 - abs(dy):
            px(xb, WALL_TOP + dy, TENT_TRIM)
# 底缘深线 + 入口
rect(TX - TR, WALL_BOT - 1, TX + TR, WALL_BOT, mix(TENT_TRIM, (0, 0, 0), 0.2))
for y in range(222, WALL_BOT + 1):
    half = int((y - 222) * 0.62) + 2
    for x in range(TX - half, TX + half + 1):
        px(x, y, (96, 52, 96))
# 旗：杆 + 实色旗面（强调物回退实色）
line(TX, APEX, TX, 76, WOOD_DARK)
for y in range(76, 85):
    for x in range(TX, TX + int((84 - y) * 1.9) + 1):
        px(x, y, FLAG_RED)


# ---------- 10. 摊位×2：红黄条纹雨棚（方向带 + 装饰纹） ----------
def stall(x0, base_y, w):
    top = base_y - 34
    for i, x in enumerate(range(x0, x0 + w)):       # 雨棚条纹
        c = STALL_YEL if (i // 6) % 2 else STALL_RED
        for y in range(top, top + 9):
            px(x, y, c)
        for y in range(top + 9, top + 12):          # 棚缘 1px 影
            px(x, y, mix(c, (0, 0, 0), 0.25))
    rect(x0 + 2, top + 12, x0 + w - 3, base_y, WOOD)        # 柜台
    rect(x0 + w - 6, top + 12, x0 + w - 3, base_y, WOOD_DARK)
    rect(x0 + 2, base_y - 8, x0 + w - 3, base_y - 6, WOOD_DARK)  # 台面线
    for x in range(x0, x0 + w):                     # 棚顶装饰短穗
        if (x - x0) % 6 == 2:
            px(x, top + 12, mix(STALL_RED, (0, 0, 0), 0.1))


stall(72, 292, 78)
stall(200, 278, 60)


# ---------- 11. 树冠：三层等方绿斑（深底 + 中斑 + 亮点） ----------
def tree(cx, cy, r, trunk_y0, trunk_y1):
    rect(cx - 5, trunk_y0, cx + 5, trunk_y1, TRUNK)
    rect(cx + 2, trunk_y0, cx + 5, trunk_y1, TRUNK_DARK)
    fill_disc(cx, cy, r, TREE_D)
    for _ in range(int(r * r / 55)):                # 中绿斑
        a, d = rng.random() * 2 * np.pi, rng.random() * r * 0.85
        fill_disc(int(cx + d * np.cos(a)), int(cy + d * np.sin(a)),
                  int(3 + rng.random() * 4), TREE_M)
    for _ in range(int(r * r / 34)):                # 亮绿点：偏受光侧（左上）
        a = rng.random() * np.pi + np.pi
        d = rng.random() * r * 0.9
        x, y = int(cx + d * np.cos(a) * 0.7 - 3), int(cy + d * np.sin(a) * 0.7 - 3)
        if (x - cx) ** 2 + (y - cy) ** 2 < r * r * 0.9:
            px(x, y, TREE_L)
            if bayer(x + 1, y) < 0.5:
                px(x + 1, y, TREE_M)


tree(44, 226, 52, 262, 316)
tree(604, 242, 55, 276, 330)


# ---------- 12. 灯：实色灯核 + 密度递减光晕 ----------
def lamp(x, top, bottom):
    line(x, top, x, bottom, POLE)
    rect(x - 5, top, x + 5, top + 2, POLE)
    rect(x - 2, top + 3, x + 2, top + 6, LAMP_CORE)      # 灯核实色
    for y in range(top - 3, top + 10):                   # 光晕：点阵密度递减
        for dx in range(-6, 7):
            d = np.hypot(dx, y - (top + 4))
            if 3 < d < 8 and bayer(x + dx, y) < max(0.0, 0.55 - d / 14):
                px(x + dx, y, LAMP_GLOW)


lamp(266, 268, 330)
lamp(414, 258, 302)


# ---------- 13. 人群：色块剪影（世界层，无描线低对比）+ 接触阴影 ----------
def person(x, y, h, c):
    head = max(2, h // 6)
    w = max(6, h // 2)
    fill_disc(x, y - h + head, head, c)
    rect(x - w // 2, y - h + head * 2, x + w // 2, y - 1, c)
    ellipse_soft(x, y, w // 2 + 2, 2, mix(SHADOW, PATH, 0.25))


person(232, 342, 18, CROWD[0])
person(250, 346, 16, CROWD[1])
person(440, 356, 20, CROWD[2])
person(492, 318, 15, CROWD[3])
person(508, 322, 14, CROWD[0])


# ---------- 14. 气球：强调色 + 1px 实色高光 + 细线 ----------
for (bx, by), c in zip([(138, 240), (150, 232), (158, 242), (146, 248)], BALLOON):
    fill_disc(bx, by, 5, c)
    px(bx - 2, by - 3, (255, 255, 255))
    line(bx, by + 5, 140, 268, WOOD_DARK)


# ---------- 15. 量化吸附 256 索引 + 输出 ----------
out = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")
n_raw = len(np.unique(out.resize((1, 1)).getbbox() and np.array(out).reshape(-1, 3), axis=0))
q = out.quantize(colors=256, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
main_path = OUT / "pc98_park_scene_640x400.png"
q.save(main_path)

colors = q.getcolors(256)
print("size:", q.size, "colors:", len(colors) if colors else ">256")
print("painted_colors:", n_raw)
print("saved:", main_path)
