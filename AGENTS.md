# AGENTS.md — pc98paint 项目指南

供 AI agent 与新协作者快速上手。改动本文件前请先读完。

## 项目是什么

把图像还原为 **PC-98 索引色绘画**（galgame CG）的研究项目：立绘、场景、以及支撑两者的 Python 管线。理论依据见 `docs/` 六篇：

- `docs/01_总体风格手法.md` — 索引色合成语法（交错点三要素、实色边界、验收指标）
- `docs/02_场景的做法.md` — 场景 CG 流程（透视、材质场、结构线、景深）
- `docs/03_人物的做法.md` — 立绘与内嵌人物
- `docs/04_用色系统与人物设计总结.md` — 五张实测参考图得出的 16 色槽位系统与人物设计规律
- `docs/05_脸部与五官设计.md` — 24 人五官与发型的分类词表、组合公式
- `docs/06_服装设计.md` — 24 人服装、领型身份表、配饰与图案规则

## 目录约定

| 路径 | 内容 |
|---|---|
| `docs/` | 理论论文（`archive/` 为旧版研究）；01 技术方案、02 美术标准、03 人物的做法、04 用色系统、05 脸部与五官设计、06 服装设计 |
| `devdocs/` | **项目文档统一目录**：需求规格（spec）、实现计划（tasks）、评审记录等 Spec Mode 产物，以及项目级设计文档，按主题分子目录存放。所有新文档一律写此处，不再使用 `.trae/specs/` |
| `refs/proportions/` | 身材比例参考图 `shinchou_01`–`31`（编号与 `docs/03` 第 14 节对应） |
| `refs/palette/` | 用色参考图 `yongse_01`–`05`（`docs/04` 的五张实测样本） |
| `refs/characters/` | `shinchou_01`–`24` 的拆图：`*_head.png`（头颈）与 `*_body.png`（颈部以下），供五官/发型/服装查阅 |
| `refs/faces/` | 五官近景参考图（`eye_ref_01.png` 竖长杏眼、`eye_ref_02.png` 圆润酒红眼），对应 `docs/05` §1.1 的定稿画法 |
| `characters/` | 角色规格 `spec.json`（比例、发色、五官等量化参数）、`palette.json`；**高清源图（人设图）与 spec.json 同目录存放** |
| `output/` | **产出资产统一目录**（640×400 PNG / 立绘 PNG + 各阶段 report/lint JSON） |
| `tools/lib/` | 共享算法核心：`pc98core.py`（场景）、`pc98_sprite_v7.py`（立绘） |
| `tools/common/` | 跨管线公共模块：取色（`palette98`/`analyze_ref`）、像素化（`pixelize`）、验收（`lint`）、spec（`schema`/`prompt`/`repair`）、参考拆图（`split_ref`） |
| `tools/sheet/` | **管线 1：三视图**（设定稿拆分、结构校验、多视图渲染） |
| `tools/tachie/` | **管线 2：立绘**（特写 / 半身 / 全身三档） |
| `tools/scene/` | **管线 3：场景**（教室 / 游乐园） |
| `tools/legacy/` | 历史脚本与面部/头部实验脚本，不再维护，仅备查 |
| `pc98/` | 历史产出存档（2026-11-21 前的旧资产，只读参考，不再写入） |
| `_work/` | 再生工作区：调试临时文件、测量半成品；已加入 `.gitignore` 不入库。**高清源图现存放于 `characters/<name>/`（与 spec.json 同目录），不再放 `_work/pc98_src/`** |

## 人物设计速查

设计一个角色按 **性别 → 年龄 → 领型 → 发型 → 一个记忆点** 的顺序填，每项只从下表取值，不自由发挥。完整依据见 `docs/05`（五官/发型）与 `docs/06`（服装）。

| 维度 | 可选值 |
|---|---|
| 眼型 | 圆（幼）/ 杏（女）/ 细（男、冷） |
| 眉型 | 粗斜 / 粗平 / 细弯 / 细平 / 下垂 |
| 鼻型 | 点（幼）/ 短竖（青年）/ L 形（成年男） |
| 嘴型 | 一线 / 短线 / 上弯 / 下弯 / 张口 |
| 领型（= 身份） | 立领（男学生）/ 水手领（女学生）/ 翻领西装（社会人）/ 宽驳领大衣（成年）/ 圆领开襟（居家） |
| 颈部配饰 | 无 / 细花纹领带 / 领巾 / 大蝴蝶结 / 冬季围巾 |
| 发型-长度 | 短 / 鲍伯 / 中长 / 长（**男性一律短**） |
| 发型-前发 | 齐刘海 / 斜分 / 中分露额 / 遮单眼 / 背头 / 刺发 |
| 发型-束发 | 无 / 双马尾 / 盘发 / 头带·头巾 |
| 发色 | 自然色 17/24；**非自然色只给学生** |
| 图案 | 只上小面积：格纹（裙/结）、条纹（衬衫）、花纹（领带）、文字（T 恤） |

硬约束：**全身档只能用「领型 + 主色 + 发型剪影（长度/束发外轮廓/发色）」识别**，五官、纽扣、格纹、刘海在 134×360 里全部丢失。

## 工具注册表

新增脚本一律放进 `tools/` 对应子目录，并在此登记。所有命令均在项目根目录执行。

| 工具 | 作用 | 典型命令 |
|---|---|---|
| `tools/sheet/sheet.py` | **管线 1 三视图**：设定稿拆分、面部结构校验、多视图渲染 | `python tools/sheet/sheet.py --from-sheet <设定稿>` |
| `tools/tachie/asset3.py` | **管线 2 立绘**：三档渲染（特写/半身/全身，640×400 透明） | `python tools/tachie/asset3.py --tier <档位> --palette output/palettes/x.json --closeup-palette output/palettes/x_closeup.json --prefix <名称>` |
| `tools/tachie/bust_sample2.py` | 管线 2 立绘：640×400 头肩样张与量化/抖动算法原型 | `python tools/tachie/bust_sample2.py` |
| `tools/tachie/pipeline.py` | 管线 2 立绘：spec 驱动的像素化 + lint + 修复循环；给出 `--palette` 时走材质区域（与 asset3 同一核心），`--legacy-render` 回退旧路线 | `python tools/tachie/pipeline.py --spec characters/xxx/spec.json --source <高清源图> --out <名称> --palette output/palettes/xxx.json --tier half` |
| `tools/scene/pc98_scene_classroom_gal.py` | 管线 3 场景：教室背景 CG → 640×400 | `python tools/scene/pc98_scene_classroom_gal.py --src _work/pc98_src/x.jpg --name classroom_x` |
| `tools/scene/pc98_scene_park_gal.py` | 管线 3 场景：游乐园背景 CG（含裁水印/16:10 示例） | `python tools/scene/pc98_scene_park_gal.py` |
| `tools/common/analyze_ref.py` | 公共：统计参考图色数、黑线占比、17 网格命中、槽位覆盖 | `python tools/common/analyze_ref.py <图> --json output/ref_analysis/x.json` |
| `tools/common/palette98.py` | 公共：生成 16 色槽位色板 JSON（12 核心 + 弹性槽） | `python tools/common/palette98.py --build skin_mid,blush,navy_mid,navy_dark --out output/palettes/x.json` |
| `tools/common/pixelize.py` | 公共：像素化核心，被 `pipeline`/`sheet` 调用 | `import pixelize` |
| `tools/common/lint.py` | 公共：成品验收（色数、黑线、中性灰、线宽） | 由 `pipeline.py` 调用 |
| `tools/common/schema.py` | 公共：`spec.json` 加载与校验 | 由 `pipeline.py`/`sheet.py` 调用 |
| `tools/common/prompt.py` | 公共：由 spec 生成图像模型提示词 | `python tools/common/prompt.py --spec <spec>` |
| `tools/common/repair.py` | 公共：局部修复，被 `pipeline`/`sheet` 调用 | 由 `pipeline.py`/`sheet.py` 调用 |
| `tools/common/split_ref.py` | 公共：按颈线把参考立绘拆成头/身两张（内置 01–24 颈线比例表） | `python tools/common/split_ref.py --src refs/proportions --out refs/characters --ids 01-24` |
| `tools/lib/pc98core.py` | 场景算法唯一实现，禁止复制 | `import pc98core` |
| `tools/lib/pc98_sprite_v7.py` | 立绘算法核心（`line_layer` 等），禁止复制 | `import pc98_sprite_v7` |
| `tools/legacy/pc98_v6.py` | core 历史调用入口（scene/tachie），仅备查 | 不再使用 |
| `tools/legacy/face_*.py`、`head_*.py`、`ascii_face.py`、`anchors_from_head.py` | 面部/头部结构实验脚本，结论已并入 `docs/03`，仅供追溯 | 按需单独运行 |

## 核心模块（改算法只改这里）

**`tools/lib/pc98core.py`** —— PC-98 索引色算法的唯一实现，无副作用、可安全 import：

- `line_layer(mid, target)` — 线稿层：2× 提线、2×2 取最大下采样成 1px 线，大片深色不算线
- `index_colors(color, lmask, lcolor, n_base=96, density=0.35)` — 索引化主流程：96 原色 + 96 同明度异色相伙伴色、平坦区方向性交错、线稿色归并 16 色
- `partner_of` / `direction` / `rotated_bayer` / `make_bayer` — 伙伴色、结构张量方向场、Bayer 交错
- `srgb_to_linear` / `rgb_to_lab` 等 — 线性光换算（配对反解必须在线性光下）

**规则：任何脚本不得复制这些函数，一律 `import pc98core`。** 调参（如交错密度、伙伴色偏移角）改 core 后所有管线同时生效。

## 三条产出路线（勿混淆）

| 路线 | 目录 | 入口 | 产出 |
|---|---|---|---|
| **1 三视图（人设图）** | `tools/sheet/` | `sheet.py` | 角色设定稿/多视图，校验比例与五官结构 |
| **2 立绘** | `tools/tachie/` | `asset3.py`、`pipeline.py` | 特写 / 半身 / 全身三档透明 PNG |
| **3 场景** | `tools/scene/` | `pc98_scene_*.py` | 640×400 索引色场景 CG |

`tools/common/`（取色、像素化、验收、spec）与 `tools/lib/`（算法核心）是三条路线共用的底层，不单独产出资产。

**术语约定（必须记住）**：「人设图」=「设定稿」=「三视图」，三者是同一样东西，统一走管线 1（`tools/sheet/`）。用户说“人设图”时，指的是角色多视图设定稿，**不是立绘、不是普通插画、也不是场景图**；出图前按这条对齐，不要理解成立绘请求。

**三视图与立绘无关**：三视图是设计稿，**不做 PC-98 像素化/索引化，也不受 640×400 等分辨率约束**，按原生高分辨率交付；640×400、16 色槽位等规则只约束立绘与场景成品。

**输出目录硬性规定**：所有成品（含三视图、立绘、场景）**一律落在 `output/`**；`output/` 与 `_work/` 已加入 `.gitignore` 不入库。高清源图（人设图）与 `spec.json` 同存于 `characters/<name>/`，不得散放于 `_work/`；高清三视图也要先写入 `output/` 再交付。

> **人物硬性约定**：本项目中用户指定“生成立绘”，一律指 **PC-98 galgame 人物立绘**，不是普通高清动漫立绘。必须遵循角色三视图与 `spec.json`，经 `tools/tachie` 像素化、索引化并通过 lint；高清或 AI 源图仅为中间素材，不得直接作为最终立绘交付。成品为透明背景 PNG，统一写入 `output/`。
>
> **场景硬性约定**：本项目产出的场景图必须是 **PC-98 galgame 风格的场景 CG** ——
> 即经 `pc98core` 索引化、640×400、256 色以内的成品。AI 生成的源图
> （`_work/pc98_src/`）只是中间素材，不得直接交付，也不得当作"场景图"引用。
> 验收时按 `docs/01_总体风格手法.md` 的指标看：有限色板、1px 线稿、方向性交错、实色边界。

### 立绘三档资产（2026-11-22 定稿：默认半身·无表情）

**用户说“生成立绘”时，默认只出半身档一张（头顶到胯），表情为无表情/平静**——不加微笑、悲伤等情绪。**特写与全身只有用户明确说出才生成**；特写在 galgame 中主要用于 CG，不作为常规表情立绘。三档均为 **640×400 透明画布、底部对齐、水平居中**；每档、每个表情都必须单独生成对应的高分辨率源图，禁止复用或缩放裁切。

| 档位 | 画布 | 人物实尺寸 | 用途 |
|---|---|---|---|
| 特写 | 640×400 | 约 576×360（居中，头肩） | CG / 对话特写（需明确指定） |
| 半身 | 640×400 | 约 238×360（头顶到胯） | **默认立绘** |
| 全身 | 640×400 | 约 134×360（头顶到鞋） | 全身立绘（需明确指定） |

三档统一遵守下列像素规则（依据 2026-11-22 参考图验证）：

- 每通道 4bit，所有颜色落在 **17 的倍数**上
- 硬阶分色；只在色阶边界做 **1–2px 棋盘交错**，不做全局 Floyd–Steinberg 抖动
- 线稿 **1px 纯黑**（Zhang-Suen 细化），不用蓝灰线
- 暗部走暖色相（浅部暖粉灰、深部蓝紫），**中性灰像素必须为 0**
- 显示只做**整数倍最近邻放大**，禁止非整数缩放
- **上下留白固定为画布高度的 5%**（640×400 即上下各 20px），三档统一；人物可用高度 360px

出图请求的解析顺序：**档位 → 表情/情绪 → 其他姿态要求**。未写档位时按**半身**，未写表情时按**无表情/平静**；表情必须写进该档源图的生成提示词（如笑、悲伤、惊讶），并据此重绘五官，不得只改嘴角像素。

**一次一档（2026-11-22 硬性禁止）**：禁止在同一轮里同时生成特写、半身、全身，也禁止同一档一次出多个表情。每轮只做 **1 档 × 1 表情**，交付后等用户确认，再做下一个。`tools/tachie/asset3.py` 已强制 `--tier` 参数，每次只渲染一档；批量出图视为违规、空耗 token。

**视角（硬性）**：立绘默认**平视**，除非用户明确要求，否则禁止仰视、俯视、高机位、低机位。源图提示词必须写 `eye-level camera, straight-on view, no high angle, no low angle`；生成后先验收视角，俯视/仰视的源图不得进入管线。

**眼部结构验收（硬性，2026-11-22）**：每张立绘必须逐项检查——
1. 两只虹膜都在，形状完整，没有一眼糊成黑块；
2. **两只眼都有高光**，位置同钟点（默认左上 10 点）、尺寸相差不超过 1px；
3. 高光**只用纯白** `white`，不得是肤色、灰绿或紫；
4. 瞳孔、上下眼线、眼镜框没有被材质归类吃掉。

任一项不合格视为出图失败，不得交付。source 阶段也要查：AI 源图经常只给一只眼画高光，这种源图先补或重生成，再进管线。实现见 `tools/tachie/matregion.py`（小面积白色不参与分带、眼内小亮块强制归白）。

**变更纪律（硬性）**：色板槽位、量化阶段、抖动策略、裁切/构图等既定设计，**未经用户确认不得删改**。实验只能放在临时副本或默认关闭的开关里，使用前先说明取舍；禁止为修单张图而私自改全局管线。

实现：`tools/tachie/bust_sample2.py`（色板与画法）、`tools/tachie/asset3.py`（单档构图）。

### 16 色槽位系统（2026-11-22 定稿）

实测五张 PC-98 参考图后确定：**整部作品共用一套 16 色**，不是每个角色一套。

- **12 色固定核心**：black、white、skin_light、red、red_dark、brown、gold、green、blue、lavender、gray_green_light、gray_green_dark
- **最多 4 个弹性槽**：skin_mid（默认必选）、pale_yellow、sky、blush、orange_brown、dark_green、brick_red、navy_dark、navy_mid
- 每材质领 **2–3 个槽位**，槽位跨材质、跨角色复用；多人同框共享肤色/黑白/背景，只按角色分配强调槽
- 全部颜色落在 **17 的倍数**；**中性灰为 0**；**黑线占比 6–20%**（目标约 12%；该比例含瞳孔与深色发块，纯线稿单人立绘会低于此值）
- 饱和度分层：背景 0.09–0.27 ＜ 肤亮 0.27 ＜ 肤中 0.46 ＜ 强调 0.50–0.64
- **线稿与噪点**：线层对比阈值 30，**禁止按色块边界描线**（会产生锯齿）；棋盘交错仅限 Lab ΔE ≤ 10 的相邻色；线层去掉小于 4px 的孤立线段；蓝发内被蓝色包围且不贴黑线的白色小岛并入 lavender
- **材质两档下限**：每个材质至少要有 base + 暗部两档。管道只做逐像素最近槽，区间里只有一档就会退化成单色 + 线稿（半身制服曾 40,759px 全落 navy_dark）。制服亮簇 L\*30 附近配 `navy_mid`，L\*35 附近配 `blue`，按材质实际亮度簇选，别硬压统一色
- **颜色去碎块**：交错后把小于 `color_min`（特写 6 / 半身 4 / 全身 3 px）的孤立色块并入周围主色，否则蓝/灰绿会留下成片杂点

管道命令：

```
python tools/common/analyze_ref.py <参考图> --json output/ref_analysis/x.json
python tools/common/palette98.py --build skin_mid,blush,pale_yellow,navy_dark --out output/palettes/x_closeup.json
python tools/common/palette98.py --build skin_mid,blush,navy_mid,navy_dark --out output/palettes/x.json
python tools/tachie/asset3.py --tier <档位> --palette output/palettes/x.json --closeup-palette output/palettes/x_closeup.json --prefix <名称>
```

**禁止**：按角色手搓色板、用 7 个相近色凑一个材质、把背景“灰”做成中性灰、用大色板弥补源图发灰。

1. **三视图**：`tools/sheet/sheet.py`，负责设定稿拆分、面部结构校验与多视图渲染，产物写入 `output/`。
2. **立绘**：`tools/tachie/pipeline.py --spec characters/xxx/spec.json --source ... --out xxx`，
   自带 lint（`*_lint.json`）与修复循环；单档渲染由 `tools/tachie/asset3.py` 负责（`--tier` 一次一档）。
3. **场景（galgame 背景 CG）**：高清源图 → `pc98core` 管线 → 640×400。
   参考脚本 `tools/scene/pc98_scene_park_gal.py`（含本项目源图的裁水印/16:10 裁切示例）。
   教室场景固定使用 `python tools/scene/pc98_scene_classroom_gal.py --src <高清源图> --name <输出名>`；可用选项调整裁切、饱和度和对比度。
   源图用图像生成模型产出（galgame 背景画风）；人物数量、位置与姿态按任务写清，默认不含可读文字。
   **禁止用程序化几何绘制直接"画"场景**——那是示意图，不是 CG（2026-11-21 已试错一次）。

`tools/legacy/pc98_v6.py` 是 core 的历史调用入口（scene/tachie 两模式），已加 `__main__` 保护，可 import。

## 运行环境

Windows + Python 3.13，依赖 `numpy / pillow / scipy`（`pip install numpy pillow scipy`）。
脚本内路径一律用 `Path(__file__).resolve().parents[...]` 相对定位，禁止绝对盘符。

## 产出命名

`output/<名称>_640x400.png` 主图（教室工具自动添加 `pc98_` 前缀）；**场景管线禁止生成 `<名称>_zoom.png` 等局部放大图**，既有旧文件仅作存档，不再更新。立绘管线的检查图不受此限制。迭代版本加后缀（`_v2`、`_A2`…），旧的 report/lint JSON 一并保留可追溯。所有管线脚本（`tools/tachie/pipeline.py`、`tools/sheet/sheet.py`、`tools/scene/*.py`、`tools/legacy/pc98_v6.py`）的输出一律落在 `output/`，`--out` 参数只给名字，不带目录。

## 场景生成与修正纪律（2026-11-21）

- 人物数量、分布、坐姿/站姿、手部动作和家具数量必须写成明确的画面约束；关键姿态同时使用正向描述与禁止项，例如“双手在桌面阅读”与“无人举手、手臂不超过肩高”。
- 先验收高清源图的构图与姿态，再进入 `pc98core`；最终仍须按 640×400 成品验收，不能用高清源图代替成品检查。
- 人体手臂、腿部等姿态修改优先整图重新生成。局部修补若残留原动作轮廓、涂抹或结构缺失，必须放弃该版本，不得继续叠补丁或作为成品交付；本次“举手改阅读”以此原则整图重生成后通过。
- 可复用任务脚本固定放在 `tools/`；源图路径与输出名必须参数化，禁止绝对盘符。共享算法只从 `tools/lib/pc98core.py` 导入，不复制实现。
