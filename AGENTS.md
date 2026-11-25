# AGENTS.md — pc98paint 项目指南

供 AI agent 与新协作者快速上手。改动本文件前请先读完。

## 项目是什么

把图像还原为 **PC-98 索引色绘画**（galgame CG）的研究项目：立绘、场景、以及支撑两者的 Python 管线。理论依据见 `docs/` 十篇：

- `docs/01_总体风格手法.md` — 索引色合成语法（交错点三要素、实色边界、验收指标）
- `docs/02_场景的做法.md` — 场景 CG 流程（透视、材质场、结构线、景深）
- `docs/03_人物的做法.md` — 立绘与内嵌人物（含 §14 体型实测、§14.1 胸围数据、§14.2 腰径参数）
- `docs/04_用色系统与人物设计总结.md` — 五张实测参考图得出的 16 色槽位系统与人物设计规律
- `docs/05_脸部与五官设计.md` — 24 人五官与发型的分类词表、组合公式
- `docs/06_服装设计.md` — 24 人服装、领型身份表、配饰与图案规则（含 §2.8 三层着装模板、§2.9 新阴影画法）
- `docs/07_管线整改.md` — 2026-11-22 立绘管线整改的目标、阶段与验收
- `docs/08_人设锁定.md` — 人设字段化、参考图与主脸派生规则
- `docs/09_材质系统.md` — 材质配置驱动与角色目录命名
- `docs/10_人设与色板流程修正.md` — momo 轮次暴露的流程问题与修正方案

**登记纪律（硬性）**：新增/修改/删除 `docs/` 页面或 `tools/` 脚本时，必须在**同一轮**更新本文件的文档清单、目录表与工具注册表；未登记视为未完成。新增 `tools/` 脚本还必须补一条可执行命令与对应测试（如适用）。

## 目录约定

| 路径 | 内容 |
|---|---|
| `STYLE_KEYWORDS.md` | **全局强制画风关键字的单一事实源**；每次出图前必读，`CREDIT` 行由 `tools/common/style.py` 自动前置，`REQUIRED` 行缺一即报错 |
| `docs/` | 理论论文（`archive/` 为旧版研究）；01 技术方案、02 美术标准、03 人物的做法、04 用色系统、05 五官、06 服装、07 管线整改、08 人设锁定、09 材质系统、10 流程修正 |
| `devdocs/` | **项目文档统一目录**：需求规格（spec）、实现计划（tasks）、评审记录等 Spec Mode 产物，以及项目级设计文档，按主题分子目录存放。所有新文档一律写此处，不再使用 `.trae/specs/` |
| `refs/proportions/` | 身材比例参考图 `shinchou_01`–`31`（编号与 `docs/03` 第 14 节对应） |
| `refs/palette/` | 用色参考图 `yongse_01`–`05`（`docs/04` 的五张实测样本） |
| `refs/characters/` | `shinchou_01`–`24` 的拆图：`*_head.png`（头颈）与 `*_body.png`（颈部以下），供五官/发型/服装查阅 |
| `refs/faces/` | 五官近景参考图（`eye_ref_01.png` 竖长杏眼、`eye_ref_02.png` 圆润酒红眼），对应 `docs/05` §1.1 的定稿画法 |
| `characters/` | 角色规格 `spec.json`（比例、发色、五官等量化参数）、`palette.json`；**高清源图（人设图）与 spec.json 同目录存放** |
| `characters/templates/archetypes/` | 三层模板层 1：24 个参考**原型** + momo 实例原型（共 25） |
| `characters/templates/outfits/` | 三层模板层 2：24 个参考**着装变体** + momo 水手装（共 25） |
| `characters/templates/index.json` | 模板注册表与自动匹配关键词 |
| `output/` | **产出资产统一目录**（640×400 PNG / 立绘 PNG + 各阶段 report/lint JSON）；**按角色名建子目录 `output/<角色名>/`**，同一角色的 brief/prompt/高清源图/PC-98 图/检查图都放其中 |
| `tools/lib/` | 共享算法核心：`pc98core.py`（场景）、`pc98_sprite_v7.py`（立绘）、`lsp.py`（LSP 契约/合成/台账） |
| `tools/common/` | 跨管线公共模块：取色（`palette98`/`analyze_ref`/`palette_for`）、像素化（`pixelize`）、验收（`lint`）、spec（`schema`/`prompt`/`repair`）、参考拆图（`split_ref`）、三层模板解析（`template`） |
| `tools/sheet/` | **管线 1：三视图**（设定稿拆分、结构校验、多视图渲染） |
| `tools/tachie/` | **管线 2：立绘**（特写 / 半身 / 全身三档；`drawing` 结构派生遮挡、`matregion` 材质渲染） |
| `tools/tachie/test_fixtures/` | 模板测试夹具（1 原型 + 2 着装变体） |
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

### 三层人物模板（2026-11-23，`docs/06` §2.8）

角色配置拆成 **原型（archetype）→ 着装变体（outfit）→ 角色实例（spec）**：

- 原型含 `body`（头身、肩宽/脸宽比、腰径/头高、胸围档位/锚点）、`face`、`hair`；着装变体含 `outfit` 提示词字段、`materials`、`garment_layers`、`drawing`。
- 解析顺序：`spec.template` 显式指定 → 否则按 `gender` + `outfit.type` + 年龄/关键词自动匹配；**face/hair 保留实例，outfit/materials/drawing/garment_layers 一律以模板为准**（`body` 深合并，实例字段覆盖）。
- 自动匹配确定性排序：分数 → `ref` → `id`；`report.json` 的 `resolved_template` 记录选中 id、来源（explicit/auto）与分数。
- **所有渲染必须走模板管线**：不得在实例里靠旧 `materials/drawing` 绕过模板；旧实例（如 momo）必须显式声明 `template`。
- 派生遮挡：`drawing.occlusions[].derive = "layer_edge"` 从 `over/under` 真实接缝向 `under` 侧取带，不再用无方向的膨胀；胸围 `bust.size ≥ 2` 时在白衣**受光背面一侧**派生 under-boob 月牙（面积上限 2.5%，单侧避免读成微笑）。白衣暗带只沿外轮廓（1.5%），贴脸/颈/发 3px 内保持白色。
- **阴影画法（新管线）**：白衣三档 `#ffffff → #adbca9 → #6d7b65`，中/深面来自源图亮度分位（sigma 8、p30/p8、min_px 300、9px 开闭、填洞）；头发五档含斜向分束高光与深紫红暗面；皮肤三档结构暗面（发际投影 + 单连通块轮廓 7% + 6% 低分位，脸部以膨胀虹膜为锚定位额带/下颌带，2×2 开闭去点）；角色区域关闭 Bayer 点阵（点阵只允许出现在背景）。暖白皮肤块（手/前臂、脸内白衣误判）必须归回皮肤，且白衣种子之后要再回收一次面部高光。线层只清布料内部 <12px 短排线（8 邻域，邻接长线豁免），头发发丝保留。
- 数据目录：`characters/templates/archetypes/*.json`、`outfits/*.json`、`index.json`；校验入口 `schema.load_template` / `schema.validate_index`。

## 工具注册表

新增脚本一律放进 `tools/` 对应子目录，并在此登记。所有命令均在项目根目录执行。**修改或删除已有脚本/文档时同样要在本轮更新本表与上方文档清单；未登记视为未完成。**

| 工具 | 作用 | 典型命令 |
|---|---|---|
| `tools/pipeline_c/__main__.py` | **管线 C 默认入口**：brief→spec→prompt→convert→verify | `python -m tools.pipeline_c brief --brief output/<slug>/brief.json --slug <slug> --out characters/<slug>/spec.json` |
| `tools/pipeline_c/convert.py` | 管线 C 转换：高清图 → 640×400 索引色立绘。参考 `naiz` 的 `mag_convert`，按 spec 色板做 CIELAB 最近色映射，背景置 index 0 透明。鼻子按「眼对定位 + 实心菱形重画」处理（无描边、肤色深档）：`--nose-scale 1.0` 保持源尺寸、`2.0` 放大两倍，默认 `0.667` 为历史行为；`--nose-half left|right` 只保留菱形的左/右半（默认 `none`） | `python -m tools.pipeline_c convert --spec characters/<slug>/spec.json --src output/<slug>/hd_knee.jpg --mode half --out output/<slug>/<slug>.png --nose-scale 2.0` |
| `tools/pipeline_c/from_sheet.py` | **立绘唯一来源**：从三视图按列切分，裁出正面视图（`--crop half --cut 0.76` 到膝），确定性、无人设漂移；带 `--spec` 时就地重画正面视图鼻子（`--nose-scale` / `--nose-half`）与嘴巴（端点锚定、向下弧形、70% 墨色） | `python -m tools.pipeline_c.from_sheet --sheet output/<slug>/hd_sheet.jpg --out output/<slug>/_front_half.png --view front --crop half --spec characters/<slug>/spec.json --nose-scale 1.5 --nose-half left` |
| `tools/sheet/sheet.py` | **管线 1 三视图**：设定稿拆分、面部结构校验、多视图渲染 | `python tools/sheet/sheet.py --from-sheet <设定稿>` |
| `tools/tachie/asset3.py` | **管线 2 立绘**：三档渲染（特写/半身/全身，640×400 透明） | `python tools/tachie/asset3.py --tier <档位> --palette output/palettes/x.json --closeup-palette output/palettes/x_closeup.json --prefix <名称>` |
| `tools/tachie/bust_sample2.py` | 管线 2 立绘：640×400 头肩样张与量化/抖动算法原型 | `python tools/tachie/bust_sample2.py` |
| `tools/tachie/pipeline.py` | 管线 2 立绘：spec 驱动的像素化 + lint + 修复循环；给出 `--palette` 时走材质区域（与 asset3 同一核心），`--legacy-render` 回退旧路线 | `python tools/tachie/pipeline.py --spec characters/xxx/spec.json --source <高清源图> --out <名称> --palette output/palettes/xxx.json --tier half` |
| `tools/scene/pc98_scene_classroom_gal.py` | 管线 3 场景：教室背景 CG → 640×400 | `python tools/scene/pc98_scene_classroom_gal.py --src _work/pc98_src/x.jpg --name classroom_x` |
| `tools/scene/pc98_scene_park_gal.py` | 管线 3 场景：游乐园背景 CG（含裁水印/16:10 示例） | `python tools/scene/pc98_scene_park_gal.py` |
| `tools/common/style.py` | 公共：**全局画风**（强制画师 `高橋ショウ`、`海月製作所`、`十重五重`、`松俊`），`with_credit()` 为所有 prompt 加前缀 | `import style; style.with_credit(<风格串>)` |
| `tools/common/analyze_ref.py` | 公共：统计参考图色数、黑线占比、17 网格命中、槽位覆盖 | `python tools/common/analyze_ref.py <图> --json output/ref_analysis/x.json` |
| `tools/common/palette_for.py` | 公共：由 spec 的材质高光色反推 16 色槽位并生成色板 JSON | `python tools/common/palette_for.py --spec characters/xxx/spec.json --out output/palettes/xxx.json` |
| `tools/common/palette98.py` | 公共：生成 16 色槽位色板 JSON（12 核心 + 弹性槽） | `python tools/common/palette98.py --build skin_mid,blush,navy_mid,navy_dark --out output/palettes/x.json` |
| `tools/common/pixelize.py` | 公共：像素化核心，被 `pipeline`/`sheet` 调用 | `import pixelize` |
| `tools/common/lint.py` | 公共：成品验收（色数、黑线、中性灰、线宽） | 由 `pipeline.py` 调用 |
| `tools/common/schema.py` | 公共：`spec.json` 与模板加载/校验（body、garment_layers、layer_edge、index） | 由 `pipeline.py`/`sheet.py` 调用 |
| `tools/common/template.py` | 公共：三层模板解析、模板优先合并、确定性自动匹配 | `import template`；`template.resolve_template(spec)` |
| `tools/tachie/drawing.py` | 管线 2：人体结构层（连续躯干/胸部椭球/投射/褶皱/高光），支持 `layer_edge` 与头发→身体投影 | 由 `matregion.py` 调用 |
| `tools/tachie/build_lsp.py` | LSP 分层立绘：初始化、逐层构建、预览、确认与阶段台账 | `python tools/tachie/build_lsp.py build --lsp characters/momo/lsp/half --only structure`（`--only lineart` 出线稿） |
| `tools/tachie/limbs.py` | LSP 结构层：头/躯干/四肢测量、比例换算与结构叠加绘制 | 由 `build_lsp.py` 调用 |
| `tools/tachie/lineart.py` | LSP 线稿层：材质区域轮廓（Marching Squares）+ 特征参数化描线，角色无关，输出 `30_lineart.png` 与检查图 | `python tools/tachie/build_lsp.py build --lsp characters/momo/lsp/half --only lineart --detect-h 1080` |
| `tools/tachie/shading.py` | 管线 2：统一 cel 阴影原语（固定光向、连续圆柱/椭球明暗场、嵌套色带、投影带） | 由 `matregion.py` / `drawing.py` 调用 |
| `tools/tachie/matregion.py` | 管线 2：材质区域渲染（分类→人体明暗场→结构层→着色；脸部/颈部/四肢共享光向） | 由 `asset3.py` 调用 |
| `tools/tachie/test_body_shading.py` | 管线 2 回归：`layer_edge` 接缝、胸部 57% 锚点、体积/投影、lean 位移、prompt 参数化 | `python -m unittest discover -s tools/tachie -p "test_body_shading.py"` |
| `tools/tachie/test_shadow_model.py` | 管线 2 回归：统一光向、连续圆柱/椭球、双腿独立暗带、投影方向、孤立发色岛回收 | `python -m unittest discover -s tools/tachie -p "test_shadow_model.py"` |
| `tools/tachie/test_drawing_pipeline.py` | 管线 2 回归：结构层折叠/材质覆盖/绘制层边界 | `python -m unittest discover -s tools/tachie -p "test_drawing_pipeline.py"` |
| `tools/tachie/test_material_pipeline.py` | 管线 2 回归：材质分类、momo 端到端、色板与面积基线 | `python -m unittest discover -s tools/tachie -p "test_material_pipeline.py"` |
| `tools/common/test_template.py` | 公共回归：模板数量/交叉引用、非法配置、模板优先合并、自动匹配确定性 | `python -m unittest discover -s tools/common -p "test_template.py"` |
| `tools/common/prompt.py` | 公共：由 spec 生成图像模型提示词 | `python tools/common/prompt.py --spec <spec>` |
| `tools/common/repair.py` | 公共：局部修复，被 `pipeline`/`sheet` 调用 | 由 `pipeline.py`/`sheet.py` 调用 |
| `tools/common/split_ref.py` | 公共：按颈线把参考立绘拆成头/身两张（内置 01–24 颈线比例表） | `python tools/common/split_ref.py --src refs/proportions --out refs/characters --ids 01-24` |
| `tools/lib/pc98core.py` | 场景算法唯一实现，禁止复制 | `import pc98core` |
| `tools/lib/pc98_sprite_v7.py` | 立绘算法核心（`line_layer` 等），禁止复制 | `import pc98_sprite_v7` |
| `tools/lib/lsp.py` | LSP 契约、场景读写、图层合成与阶段台账核心 | 由 `build_lsp.py` 调用 |
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

**全局画风（强制）**：关键字唯一载体是根目录 `STYLE_KEYWORDS.md`，**每次出图前必须先读该文件**；所有出图 prompt 的画风前缀统一来自 `tools/common/style.py` 的 `with_credit()`（导入时读取并校验该文件），必须携带 `高橋ショウ`、`海月製作所`、`十重五重`、`松俊`；三条路线（三视图 / 立绘 / 场景及管线 C）都走这一处，禁止在各自模块里另写画风前缀。**泳装画面还必须追加 `SWIM_REQUIRED` 条款**（管线 C 检测到 `spec.outfit.type` 含 `swim` 时自动追加，缺条款即报错）。**面部不设任何强制条款**（用户要求删除眼睛、鼻子、嘴巴的强制词）：五官的形状与画法由各角色提示词自行决定，全局仅保留 `BODY_REQUIRED` 中「眼线位于头部中线」这一比例约束，避免眼睛挤在脸上半部造成幼态。**`BODY_REQUIRED` 身材条款同样强制**：90 年代 galge 比例，约 7.5 头身、椭圆脸（高约为宽的 1.3 倍）、眼线位于头部中线、细颈、自然肩宽、腰部平直且胯部不外扩、手部与脚部正常大小，禁止 Q 版 / SD / 大头短肢 / 宽圆脸 / 婴儿脸比例。新增/调整强制项只改 `STYLE_KEYWORDS.md`，不得只改代码或只改文档。

**术语约定（必须记住）**：「人设图」=「设定稿」=「三视图」，三者是同一样东西，统一走管线 1（`tools/sheet/`）。用户说“人设图”时，指的是角色多视图设定稿，**不是立绘、不是普通插画、也不是场景图**；出图前按这条对齐，不要理解成立绘请求。

**三视图与立绘无关**：三视图是设计稿，**不做 PC-98 像素化/索引化，也不受 640×400 等分辨率约束**，按原生高分辨率交付；640×400、16 色槽位等规则只约束立绘与场景成品。

**输出目录硬性规定**：所有成品（含三视图、立绘、场景）**一律落在 `output/`**；`output/` 与 `_work/` 已加入 `.gitignore` 不入库。高清源图（人设图）与 `spec.json` 同存于 `characters/<name>/`，不得散放于 `_work/`；高清三视图也要先写入 `output/` 再交付。

**按角色分目录（强制，自 2026-11-25 起）**：今后所有与角色相关的输出物（brief、prompt、高清源图、PC-98 立绘、检查图、report/lint JSON）一律写入 `output/<角色名>/`，不再使用 `output/pipeline_c/<slug>/` 等中间层，也不得把多个角色的文件平铺在 `output/` 根下。角色名取 `characters/<角色名>/` 的目录名（如 `output/momo2/`）。

> **人物硬性约定（2026-11-25 修订）**：用户指定“生成立绘”时，默认交付 **高清立绘**（由三视图正面裁切、保持原生分辨率），**不生成 PC-98 用图**——除非用户明确要求「PC-98 / 640×400 / 进游戏素材」，才执行 `tools/tachie` 或 `pipeline_c convert` 的像素化、索引化与 lint 验收。任何情况下立绘都必须遵循角色三视图与 `spec.json`，不得为立绘重新文生图。所有成品统一写入 `output/<角色名>/`。
>
> **场景硬性约定**：本项目产出的场景图必须是 **PC-98 galgame 风格的场景 CG** ——
> 即经 `pc98core` 索引化、640×400、256 色以内的成品。AI 生成的源图
> （`_work/pc98_src/`）只是中间素材，不得直接交付，也不得当作"场景图"引用。
> 验收时按 `docs/01_总体风格手法.md` 的指标看：有限色板、1px 线稿、方向性交错、实色边界。

### 立绘三档资产（2026-11-22 定稿：默认半身·无表情）

**PC-98 转换默认关闭（2026-11-25 用户要求）**：生成立绘时**不再默认产出 640×400 索引色成品**，只交付高清立绘（三视图正面裁切）。下表三档与 `pipeline_c convert` / `tools/tachie` 仅在用户明确要求 PC-98 用图时启用；未要求时跳过转换、不做 lint，也不得把转换图当作默认交付物。

**用户说“生成立绘”时，默认只出半身档一张（头顶到胯），表情为无表情/平静**——不加微笑、悲伤等情绪。**特写与全身只有用户明确说出才生成**；特写在 galgame 中主要用于 CG，不作为常规表情立绘。三档均为 **640×400 透明画布、底部对齐、水平居中**。**立绘源图必须由三视图的正面视图裁切得到**——`python -m tools.pipeline_c.from_sheet --sheet output/<角色名>/hd_sheet.jpg --out output/<角色名>/_front_half.png --view front --crop full|half --cut 0.50`；**禁止为立绘重新文生图**（独立采样会让发型、脸型、服装细节漂移）。`--cut 0.50` = 默认半身（头顶到胯，脸部像素最多）；用户明确要求到膝时用 `--cut 0.76`。不同档位/画幅只允许在同一张三视图上换裁切比例，不得重新生成。

**鼻子与嘴巴强制修正落在三视图上（2026-11-25 用户要求）**：出图后必须对**三视图本身**执行 `--spec`——鼻子按 `--nose-scale 1.5 --nose-half left` 重画为左半实心菱形（肤色 shadow 档、无描边），嘴巴按「**原嘴线的两个端点做锚点、中间向下弧形下压**」重画为单条细弧线（线色 = 脸部最暗 12% 均值与肤色的 70/30 混合，即比原线色浅 30%；2px 抗锯齿、微笑）。侧面/背面无正面五官，不处理。命令：`python -m tools.pipeline_c.from_sheet --sheet output/<角色名>/hd_sheet.jpg --out output/<角色名>/_front_half.png --view front --crop half --spec characters/<角色名>/spec.json --nose-scale 1.5 --nose-half left`（`--spec` 会就地重写 sheet）。鼻子定位先用虹膜对推鼻位，再用**画面里实际画出的暗色鼻影连通块**对齐（`at=eyes+drawn`）；嘴巴端点取正面脸下半部、鼻下 0.18–0.44 瞳距带内的浅色短标记的并集 bbox。查找失败分别回落 `at=eyes`/`at=chin` 与鼻下 `+0.30×瞳距` 预测位，并在串口日志体现。改图前先备份原始 sheet（如 `hd_sheet_raw.jpg`）。两条重画均为**幂等**：鼻腔命中「已是目标尺寸的菱形」输出 `NOSE: skip already fixed`；嘴部沿弧线取 5 个探针点、≥4 个已是线色即 `MOUTH: skip already fixed`（避免 JPEG 位移造成每次运行漂移）。

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

**Windows / Linux 双平台**，Python 3.12+（Windows 建议 3.13），依赖 `numpy / pillow / scipy`。依赖清单固定在 `requirements.txt`。

项目内虚拟环境统一放 `.venv/`（已 gitignore；naiz 等其它项目不要共用）：

```
# Linux
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
# Windows (PowerShell / cmd)
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

之后所有命令用 `.venv` 的解释器执行（Windows 为 `.venv\Scripts\python`，Linux 为 `.venv/bin/python`）。若系统缺少 `python3-venv`，可改用 `uv venv .venv` 后 `uv pip install -r requirements.txt`。

脚本内路径一律用 `Path(__file__).resolve().parents[...]` 相对定位，禁止绝对盘符；文本读写一律显式 `encoding="utf-8"`。测试命令：

```
python -m unittest discover -s tools/tachie -p "test_*.py"
python -m unittest discover -s tools/common -p "test_*.py"
```

## 产出命名

`output/<名称>_640x400.png` 主图（教室工具自动添加 `pc98_` 前缀）；**场景管线禁止生成 `<名称>_zoom.png` 等局部放大图**，既有旧文件仅作存档，不再更新。立绘管线的检查图不受此限制。迭代版本加后缀（`_v2`、`_A2`…），旧的 report/lint JSON 一并保留可追溯。所有管线脚本（`tools/tachie/pipeline.py`、`tools/sheet/sheet.py`、`tools/scene/*.py`、`tools/legacy/pc98_v6.py`）的输出一律落在 `output/`，`--out` 参数只给名字，不带目录。

## 场景生成与修正纪律（2026-11-21）

- 人物数量、分布、坐姿/站姿、手部动作和家具数量必须写成明确的画面约束；关键姿态同时使用正向描述与禁止项，例如“双手在桌面阅读”与“无人举手、手臂不超过肩高”。
- 先验收高清源图的构图与姿态，再进入 `pc98core`；最终仍须按 640×400 成品验收，不能用高清源图代替成品检查。
- 人体手臂、腿部等姿态修改优先整图重新生成。局部修补若残留原动作轮廓、涂抹或结构缺失，必须放弃该版本，不得继续叠补丁或作为成品交付；本次“举手改阅读”以此原则整图重生成后通过。
- 可复用任务脚本固定放在 `tools/`；源图路径与输出名必须参数化，禁止绝对盘符。共享算法只从 `tools/lib/pc98core.py` 导入，不复制实现。
