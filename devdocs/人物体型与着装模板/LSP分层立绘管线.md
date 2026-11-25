# LSP 分层立绘管线（tachie/2）

> 状态：**实施中**（v1 = 契约 + 形体结构层）
> 最后更新：2026-11-25
> 前置结论：`阴影模型重构.md`、`阴影视觉QA-逐条修复进度.md`

## 一、为什么要改

旧管线在 **640×400 成品尺度**上完成材质分类、阴影、高光与 16 色量化（`asset3.render`
先把源图缩到半身约 238×360，再交给 `matregion.render_spec`）。后果：

1. 源图自带的旧漫画阴影在 BOX 缩放后仍留在底图上；
2. 新画的阴影与旧阴影叠加，无法分离；
3. 明暗、线条、调色三个决策耦合在一个函数里，任何一层出错都必须重跑整张图；
4. 人体结构（头轴、躯干、胸椭球）只存在于内存与检查图中，不是可复用资产。

目标链条：

```
三视图（设计依据，不像素化）
      ↓
原图 LSP（源分辨率，所有细节在此完成）
  base / detail / shade / highlight / lineart
  structure（结构线+四肢，仅参考） + material（材质编号，仅转档用）
      ↓
PC-98 转档（只做尺寸/色槽/17 网格/1px 线/lint）
```

## 二、已确认的决策

| 项 | 决定 |
|---|---|
| 工作分辨率 | **原图分辨率**（半身源图为 1597×2221） |
| 明暗来源 | 现有算法出自动草稿层；base 锁定，其余层可整层替换 |
| 旧管线 | 不做长期双轨；转档器验收通过后删除 `asset3` 旧入口 |
| 结构层 | 头轴、肩腰、躯干、胸椭球 **+ 双臂/双腿骨骼与关节圆圈** |
| 结构用途 | 既供人工/AI 对齐，也作为四肢圆柱明暗场的轴 |
| 实施方式 | 先写代码，再逐层生成 PNG，逐层人工确认 |

## 三、目录与文件

```
characters/<name>/lsp/<tier>/
├── scene.json
├── structure.json
├── materials.json
├── stages.json
├── layers/
│   ├── 00_base.png
│   ├── 05_detail.png
│   ├── 10_shade.png
│   ├── 20_highlight.png
│   ├── 30_lineart.png
│   ├── 90_structure.png   # export:false
│   └── 95_material.png    # export:false, index8
└── composite.png
```

成品仍在 `output/<名称>.png`；检查图允许放 `output/`，不视为成品。

## 四、数据契约

### 4.1 scene.json

```json
{
  "format": "lsp/1",
  "profile": "tachie/2",
  "character": "momo",
  "tier": "half",
  "spec": "characters/momo/spec.json",
  "source": "characters/momo/girl_v3_half_hi.jpg",
  "canvas": { "width": 1597, "height": 2221 },
  "unit": 6.169444,
  "target": { "canvas": [640, 400], "figure_h": 360, "margin_y": 20 },
  "palette": "characters/momo/palette.json",
  "palette_groups": "palette_groups.json",
  "materials": "materials.json",
  "structure": "structure.json",
  "layers": [
    { "id": "base",      "file": "layers/00_base.png",      "role": "base",      "blend": "normal",   "opacity": 1.0, "locked": true },
    { "id": "detail",    "file": "layers/05_detail.png",    "role": "detail",    "blend": "normal",   "opacity": 1.0 },
    { "id": "shade",     "file": "layers/10_shade.png",     "role": "shade",     "blend": "multiply", "opacity": 0.85, "clip": true },
    { "id": "highlight", "file": "layers/20_highlight.png", "role": "highlight", "blend": "screen",   "opacity": 0.90, "clip": true },
    { "id": "lineart",   "file": "layers/30_lineart.png",   "role": "lineart",   "blend": "normal",   "opacity": 1.0 },
    { "id": "structure", "file": "layers/90_structure.png", "role": "structure", "blend": "normal",   "visible": false, "export": false },
    { "id": "material",  "file": "layers/95_material.png",  "role": "mask",      "encoding": "index8", "export": false }
  ]
}
```

- `unit = canvas.height / 360`，PC-98 像素到工作像素的比例。
- `export:false` 的层永不进入合成。
- `base.locked` 必须为 true。

### 4.2 structure.json

在头轴/肩腰/躯干/胸椭球之外，包含头部椭圆、胸下腰圆、盆腔椭圆与 `limbs`：

```json
{
  "unit": 6.169444,
  "head": { "x": 804.0, "top": 62.0, "cx": 836.0, "cy": 426.0,
            "rx": 298.0, "ry": 364.0, "tilt": 0.086, "chin": [867.0, 790.0],
            "axis": [[659.0, 62.0], [867.0, 790.0]] },
  "shoulder_y": 827.0, "waist_y": 1493.0,
  "shoulder_line": [[561, 950], [1132, 1012]],
  "waist_line": [[555, 1454], [919, 1532]],
  "waist": { "cx": 737.0, "cy": 1493.0, "rx": 182.0, "ry": 182.0, "tilt": -0.214 },
  "pelvis": { "cx": 645.0, "cy": 1871.0, "rx": 373.0, "ry": 177.0, "tilt": -0.214 },
  "torso": { "center_x": 799.0, "left": 462.0, "right": 1136.0,
             "width": 674.0, "sway_deg": -12.09, "center_source": "seam" },
  "bust": { "size": 2, "lobes": [
    { "cx": 690.0, "cy": 1080.0, "rx": 130.0, "ry": 100.0 } ] },
  "seams": { "left": [[...]], "right": [[...]] },
  "limbs": {
    "arms": [
      { "id": "arm_left", "side": "left", "visible": true, "partial": true,
        "fore_estimated": true, "shoulder": [561, 950], "elbow": [370, 1357],
        "visible_from": [369, 1400], "visible_to": [370, 1579],
        "wrist": [629, 1809], "hand": null, "widths": { "upper": 133, "fore": 111 },
        "joint_r": { "shoulder": 67, "elbow": 56, "wrist": 56 },
        "source": "forearm" }
    ],
    "legs": [
      { "id": "leg_left", "side": "left", "visible": true, "partial": true,
        "hip": [506, 1916], "knee": null, "ankle": null,
        "foot": null, "widths": { "thigh": 116, "shin": 72 },
        "joint_r": { "hip": 58, "knee": null, "ankle": null },
        "source": "proportional" }
    ]
  },
  "overrides": "structure.manual.json"
}
```

规则：

- 坐标一律是 LSP 工作画布坐标，与 `95_material.png` 同网格。
- 关节 = 圆心 + 半径；骨骼 = 关节间连线。
- `head.axis` 是穿过口鼻带的中线；头椭圆以该中线中点为中心、以中线斜率作为 `tilt`，
  圆弧始终跟随中线。
- 腰圆直径 = `head_h × body.waist_ratio`，必须满足 `rx=ry`；momo 的 `waist_ratio=0.62`。
- `partial:true` 表示骨骼轴包含遮挡或估计部分；完整实测轴画实线，否则整轴保守画虚线。
- `shoulder_line` 是肩骨线，两个端点必须与左右手臂的 `shoulder` 完全相同。
- 手臂始终包含肩/肘/腕；肘点落在可见前臂皮肤内（自皮肤上缘 40%），肘→腕只画一条直线。
  `visible_from/visible_to` 仅保存皮肤测量，不作为骨骼折点；背手腕部标 `fore_estimated:true`。
- 双腿始终包含髋点与单条大腿轴；膝/踝按 `proportions.heads` 定位，超出工作画布时记为 `null` 并标 `cropped:true`。
- `structure.manual.json` 存在时逐字段覆盖自动值（`source:"manual"`），重跑检测不覆盖。

### 4.3 stages.json

```json
{
  "order": ["base", "structure", "detail", "shade", "highlight", "lineart"],
  "stages": {
    "structure": { "sha256": "...", "status": "pending", "updated": "2026-11-25T10:00:00" }
  }
}
```

- `status`: `pending` / `confirmed` / `stale`。
- 上游层被重建且哈希变化 → 依赖它的下游 `confirmed` 自动转 `stale`。
- 依赖表：`detail/shade/highlight ← base, structure`；`lineart ← base, detail`。

## 五、模块

| 文件 | 职责 | 状态 |
|---|---|---|
| `tools/lib/lsp.py` | scene 读写、校验、合成（`export:false` 过滤、clip、blend）、阶段台账 | v1 |
| `tools/tachie/limbs.py` | 骨架化、分支分类、四肢关节/宽度/遮挡、结构图绘制 | v1 |
| `tools/tachie/build_lsp.py` | `init / build --only / preview / confirm / status` | v1（structure/lineart） |
| `tools/tachie/lineart.py` | 实测区域轮廓（Marching Squares）+ 特征参数化线稿，角色无关 | v1 |
| `tools/tachie/convert.py` | LSP → 640×400、色槽映射、1px 线、lint | 待实现 |
| `tools/tachie/matregion.py` | 分类阈值支持 `scale` 参数；拆出平涂/细节 | 部分 |
| `tools/tachie/asset3.py` | 旧入口 | 待删除 |

## 六、算法

### 6.1 尺度归一

旧阈值以 640×400 成品像素为单位，工作尺度换算：

```
area  → 旧值 × scale²
radius/line → 旧值 × scale
```

`build_lsp` 在检测尺度（高 720px，`scale=2`）调用 `classify_materials(..., scale=2)`，
再把结构坐标乘以 `canvas_h / 720` 映射回工作画布。这样既复用既有阈值调参，
又避免在 1597×2221 上直接跑受小图尺度影响的规则。

### 6.2 形体结构

1. 人体掩码 = 材质角色 `skin/white/cloth/accent` 的并集，排除头发。
2. **头部**：从肩线以上最大皮肤连通域测量面部最宽带与下巴，脖颈窄段不计入头高。
   头椭圆上缘取头顶、下缘取下巴，纵横半径沿用实测头高；中心取 `head.axis` 中点，
   `tilt` 取中线斜率，使圆弧随中线一起倾斜/平移。中线由最宽带中心投影到头高 70% 的
   口鼻带，与下巴连线后延长到头顶；不能用含头发/颈部的局部下颌行中心代替。
3. **姿态轴与腰/盆腔**：沿用 `chest_v8` 的躯干中轴与接缝。阴影用的 `waist_y` 保持不动，
   同时作为胸下腹部腰圆的中心高度；腰圆取 `rx=ry=0.5×head_h×body.waist_ratio`。
   画面下部最大衣物连通域（裙子）上缘只作为盆腔参考 `anatomy_waist_y`：
   盆腔中心在裙腰下 `0.30×(裙腰高-肩线高)`，横半径来自裙跨横截面，纵半径为该肩腰距的 `0.24`。
   站立姿态的髋线保持水平（盆腔 `tilt=0`），不继承躯干 sway，否则左右髋点会一高一低。
4. **角色比例**：`full_h = head_h × proportions.heads`（momo 为 6.2），用于定位膝/踝高度；
   头、腰、盆腔和四肢共用同一检测坐标系，再统一映射回工作画布。
5. **手臂**：肩关节取 `0.28×head_h×body.shoulder_ratio` 的半跨距，中心沿躯干轴定位，
   基准高度为 `shoulder_y+0.07H`，再按姿态倾斜；因此关节位于衣服肩线以下、衣袖内部，
   而不是袖管外缘。红色肩骨线直接取左右最终肩点。肘点取同侧可见前臂皮肤上缘往下 40% 的
   高度、该带皮肤中位 x，再吸附到人体掩码——袖口是布料边缘，把肘点钉在皮肤上缘会让
   关节明显高于可见小臂；上臂宽度在肩肘中点采样。肘→腕始终只画一条直线，不绕经
   `visible_from/visible_to`；背手时整条估计前臂画虚线并标 `fore_estimated:true`。
6. **腿**：可见皮肤连通域只用于确定大腿方向、可见段和宽度，不把裙摆当皮肤。髋点先按
   水平盆腔坐标系定位（纵向 `0.36×pelvis_ry`），再以 `visible_to.x-sign×0.08×torso_width`
   校准水平位置并限制在盆腔横径内，保留左右不对称站姿。大腿从髋点到可见段下缘/膝点只画
   一条直线；含裙下遮挡时整轴画虚线。膝/踝超出画布时对应坐标为 `null`，并标 `partial/cropped`。
7. 宽度：沿骨骼采样距离变换；关节圆半径 = 局部宽度/2，并设上限
   （上臂 ≤0.06H、前臂 ≤0.05H、大腿 ≤0.14H、小腿 ≤0.10H），防止 EDT 被躯干或裙摆
   等大块区域污染。

### 6.3 结构图

- 头部椭圆、腰圆、盆腔椭圆及头轴/肩腰/躯干：红；胸椭球：黄；手臂：橙；腿：绿；
  手掌/脚掌端点：青。腰部必须满足 `rx=ry`；头部椭圆跟随 `head.axis` 的倾斜，
  站立时盆腔 `tilt=0` 使髋线水平。
  胸侧 `seams` 仅保留测量数据，不作为结构叠加图的 primitive 绘制。
- 线宽 `2×unit`，关节为空心圆；前臂与大腿各自只画一条直线，不拼接实虚线折线。
  含遮挡或比例估计的整条骨骼轴用虚线，完全实测的骨骼轴才用实线。
- `90_structure.png` 为透明叠加层，`visible:false, export:false`。
- 检查图 `output/<name>_structure_check.png`：源图 65% 白洗 + 结构叠加，缩到高 900px。

## 七、逐层确认流程

```bash
python tools/tachie/build_lsp.py init --spec characters/momo/spec.json \
  --source characters/momo/girl_v3_half_hi.jpg --tier half \
  --out characters/momo/lsp/half
python tools/tachie/build_lsp.py build --lsp characters/momo/lsp/half --only structure
python tools/tachie/build_lsp.py preview --lsp characters/momo/lsp/half --layer structure
python tools/tachie/build_lsp.py confirm --lsp characters/momo/lsp/half --layer structure
python tools/tachie/build_lsp.py status --lsp characters/momo/lsp/half
```

顺序（经本轮确认调整为结构优先）：

| 步 | 层 | 确认点 |
|---|---|---|
| B1 | structure | 头颅/胸下腰圆/盆腔、肩骨线、胸椭球、完整大小臂与大腿骨骼是否贴合 |
| B2 | base | 剪影、构图、平涂配色，源图旧阴影是否清除 |
| B3 | detail | 双眼形状/位置/高光同钟点、嘴、花纹 |
| B4 | shade | 光向、胸下/腋下/裙摆、四肢圆柱暗面分臂分腿 |
| B5 | highlight | 鼻梁/锁骨/发丝高光，不溢出剪影 |
| B6 | lineart | 线稿走向、发丝、衣褶 |
| B7 | composite | 原图整体 |
| B8 | PC-98 | 640×400、16 色、黑线、眼高光、无中性灰 |

下游生成不强制等待上游确认，但转档要求全链 `confirmed`；上游哈希变化会把下游置 `stale`。

## 八、验收

1. 腰圆位于胸部下方且 `rx=ry`；头椭圆中心落在 `head.axis` 中点且 `tilt` 与该中线斜率一致；
   肩骨线两端与左右肩点逐值一致；双臂有完整肩/肘/腕，肘点位于可见小臂皮肤内；
   站立时盆腔 `tilt=0`，两髋点同高；前臂与大腿均为不绕经 `visible_from/visible_to` 的
   单段直线；双腿髋点位于盆腔下部两侧并保留大腿轴。背手腕部标 `fore_estimated`，
   画框裁切的大腿标 `partial/cropped`，出画布的膝/踝/脚允许为 `null`。
2. 实测关节圆心落在人体掩码内，半径与局部宽度误差 ≤ `2×unit`；估计关节必须显式标记。
3. 完全实测的骨骼轴用实线；含遮挡或比例估计的整条轴用虚线，不得拼接实虚线折线或伪装成实测。
4. 结构层与材质层不出现在任何合成/成品中。
5. PC-98 成品 lint：色数 ≤16、中性灰 0、黑线 6–20%、双眼纯白高光、虹膜不落灰褐槽。
6. 每层可单独重建，输出确定；阶段台账能正确传播 `stale`。

## 九、风险

| 风险 | 对策 |
|---|---|
| 骨架在 720 尺度仍被头发/衣褶污染 | 人体掩码排除头发；短分支丢弃；人工 `structure.manual.json` 兜底 |
| 手臂藏在背后，检测不到腕 | 腕部按姿态估计并标 `fore_estimated`；前臂只画一条直线，含估计部分时整轴画虚线，不虚构手部实测圆 |
| 半身画框裁到大腿 | 保留完整大腿轴，腿标 `partial/cropped`，出画布的膝/踝为 `null` |
| 类别阈值放大后漂移 | 复用 `classify_materials(scale=)`，先结构层目视校验再进入明暗 |
| 结构层被误导出 | `export:false` + 合成过滤 + 守卫测试 |

## 十、当前进度（v1）

- 已实现：`lsp.py` 契约/合成/台账；`limbs.py` 四肢检测与结构绘制；`build_lsp.py` 的
  `init/build --only structure/preview/confirm/status`。
- 本轮产出：`characters/momo/lsp/half/` 的 `scene.json`、`structure.json`、
  `layers/90_structure.png`、`output/momo_half_structure_check.png`。
- 当前状态：`structure` 阶段 `pending`，等待人工确认。momo 使用 `proportions.heads=6.2`；
  头部由实测下巴定位，头椭圆以口鼻中线的中点为中心并跟随其倾斜；腰部为胸下的圆，
  `body.waist_ratio=0.62`，裙腰与裙跨只用于盆腔定位，胸侧 `seams` 不绘制。肩点位于衣服
  肩线以下、衣袖内部，红色肩骨线由左右最终肩点生成；肘点落在可见小臂皮肤内（上缘往下
  40%），前臂和大腿均为单段直线，含遮挡/估计部分时整轴画虚线。盆腔椭圆保持水平、纵向
  `0.24×肩腰距`，两侧髋点同高（`0.36×pelvis_ry`）并按可见大腿方向校准水平位置；源图画框
  裁到大腿，出画布的膝/踝/脚不写入坐标（最新构建 `arms=2 legs=2 partial=4`，
  stage `6eb950bbe0be`）。
- 待实现：`base/detail/shade/highlight` 的生成、`convert.py`、旧入口删除。

### 十.1 线稿层 v1（2026-11-25）

- 新文档 `角色线稿生成机制.md` 定义「结构图 → 线图」契约；实现 `tools/tachie/lineart.py`。
- 输入三类、角色无关：`structure.json` 骨架 + 六 role 材质掩码 + archetype/outfit 特征描述。
- 流程：材质掩码 → Marching Squares → Chaikin 平滑 → 分级线宽描线；五官按虹膜锚点，
  纽扣沿躯干轴，裙褶按裙区上下跨度，领条为领缘内缩 loop。
- 入口：`build --only lineart --detect-h 1080`；产出 `layers/30_lineart.png` 与
  `output/<角色>_<档位>_lineart_check.png`、`..._lineart_overlay.png`；阶段仍为 `pending`。
- 结构层重建后线稿层哈希失效，必须重跑 `--only lineart`。
