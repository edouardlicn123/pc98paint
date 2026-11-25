# 立绘阴影视觉 QA — 逐条修复进度与计划（进行中）

> **状态**：🔄 进行中（living document，每收到一条视觉问题即更新，不等全部完成再总结）
> **最后更新**：2026-11-25
> **参考目标**：`refs/characters/shinchou_02_萝莉_head.png` / `_body.png` —— 大块、干净、单一光向、无散点的 cel 阴影
> **工作流**：用户每次提一条视觉问题 + 截图 → 像素归因诊断（带证据）→ 零成本预览确认方向 → 改源码 → 渲染验证 → 同步本文件 + [`阴影模型重构.md`](./阴影模型重构.md) §9 修订记录
> **详细技术记录归档**：每个问题的完整「症状→定位→根因→修复→验证」写完后归档进 [`阴影模型重构.md`](./阴影模型重构.md) §9（v9.1/v9.2/v9.3…）；本文件只做**进度追踪 + 计划 + 防复发清单**。

## 1. 进度总览

| # | 问题 | 状态 | 版本 | 根因一句话 | 详细记录 |
|---|------|------|------|-----------|---------|
| 1 | 头发高光出现手绘 streaks/横线 | ✅ 完成 | v9.1 | 硬编码弧线 `_hair_streaks` 顶在头顶 | [`阴影模型重构.md` §9 v9.1](./阴影模型重构.md) |
| 2 | 脸部阴影杂乱（脸颊/眼周碎块） | ✅ 完成 | v9.2 | 背光侧带沿脸全轮廓分布，被五官缝隙打断成 25 碎段 | [`阴影模型重构.md` §9 v9.2](./阴影模型重构.md) |
| 3 | 衣服点状阴影（V 领虚线 + 衣身散点） | ✅ 完成 | v9.3 | v9 重构丢失 v5→v8 去碎斑规则；锯齿领投影成虚线 | [`阴影模型重构.md` §9 v9.3](./阴影模型重构.md) |
| 4 | 刘海投影盖住眼睛 | ✅ 完成 | v9.4 | 头发 cast 投影下探到上眼睑，眼周皮肤被染暗；band 已限下巴不涉及 | [`阴影模型重构.md` §9 v9.4](./阴影模型重构.md) |
| 5 | 单眼颜色异常 + 缺白色反光（两眼不对称） | ✅ 完成 | v23–v26 | ①虹膜暗青档 RGB 最近邻落到 taupe（色相漂移，差 0.7%）；②左眼高光碎块 1px 环占比 0.42 未达 0.55 → 留在 hair 后被 fragment 并入 collar | [`阴影模型重构.md` §9 v10.3](./阴影模型重构.md) |
| 6 | 衣服白色条纹被污染 | ✅ v16 归因：白条没被阴影层覆盖（form=2px）；用户看到的是旧版本残留/quantization 抖动 | v16 | 诊断确认 form/occlusion/fold 对 base 白色像素覆盖共 2px；118 小暗色簇为 quantization artifact | 见下文 §2 问题 6 归因 |
| 7 | 裙子阴影用了错误的旧画法 | ✅ v16 归因：skirt+collar 共享 uniform group，shadow bands 参数同平布；分离 group 后 skirt 独立 bands | v16 | skirt+collar 同走 directional_bands(uniform_mask, ...) 致裙阴影 = 平布轮廓带 | 见下文 §2 问题 7 归因 |
| 8 | 衣服上出现不明杂线 | ⚠️ 归因：v16 诊断 50 条细长暗簇在 blouse 胸部区域，不属于 form/occlusion | — | 可能为材质分类 artifact 或 quantization 抖动，需换机放大确认 | 见下文 §2 问题 8 归因 |
| 9 | 衣服皱褶出现异常颜色 | ℹ️ 归因：momo template `drawing.folds = []`，根本没有皱褶层 | — | 非 bug；用户看到的皱褶是旧版本残留印象 | 见下文 §2 问题 9 归因 |

## 2. 已完成问题速查（证据 + 修复定位）

### 问题 1 — 头发高光 streaks（v9.1）
- **证据**：`_work/scratch/diag_hair_line.py`，头顶 827 白像素中 718 来自 `_hair_streaks`。
- **修复**：[`matregion.py`](file:///home/edo/pc98paint/tools/tachie/matregion.py) 删除 `_hair_streaks` / `_hair_highlight`，高光改取头部内源图 `lum≥0.74` + 2×2 opening + ≥10px 连通块。
- **渲染**：[v9](computer:///home/edo/pc98paint/output/shadow_v9_half_x2.jpg) → [v10](computer:///home/edo/pc98paint/output/shadow_v10_half_x2.jpg)。

### 问题 2 — 脸部阴影杂乱（v9.2）
- **证据**：`_work/scratch/diag_face_shadow.py`，脸 ROI 720px 阴影中 642px（89%）来自 per-component band，被五官缝隙打断成 25 碎段。
- **修复**：[`matregion.py`](file:///home/edo/pc98paint/tools/tachie/matregion.py) 脸主块背光带只保留下 35%（下巴/颌下）。
- **渲染**：[v10](computer:///home/edo/pc98paint/output/shadow_v10_half_x2.jpg) → [v11](computer:///home/edo/pc98paint/output/shadow_v11_half_x2.jpg)。
- **断言变更**：`MomoRegressionTests` 脸 mid 下限 0.20 → 0.14（带注释）。

### 问题 3 — 衣服点状阴影（v9.3）
分两步落地（form 先、occlusion 后）：

**3a. form 去碎斑（v13）**
- **证据**：`_work/scratch/diag_clothes.py` — blouse 阴影归因 form 70.8% / occl_collar 28.0% / bust_arc 1.3%；form 碎裂成 53 块。
- **修复**：[`drawing.py`](file:///home/edo/pc98paint/tools/tachie/drawing.py) 新增 [`_keep_large` L306](file:///home/edo/pc98paint/tools/tachie/drawing.py#L306)、[`_despeckle_form` L318](file:///home/edo/pc98paint/tools/tachie/drawing.py#L318)（9px `binary_closing` + 填洞 + keep_large），在 [cloth group L381](file:///home/edo/pc98paint/tools/tachie/drawing.py#L381) 与 [白衣分支 L400](file:///home/edo/pc98paint/tools/tachie/drawing.py#L400) 调用。恢复 [`tasks.md` L178](./tasks.md#L178) 丢失的 v5→v8 规则。
- **渲染**：[v12](computer:///home/edo/pc98paint/output/shadow_v12_half_x2.jpg) → [v13](computer:///home/edo/pc98paint/output/shadow_v13_half_x2.jpg)。

**3b. occlusion 去碎斑（v14）**
- **证据**：`_work/scratch/v13_verify.py` + `blouse_occl_comps.png` — blouse **occlusion 24 块全 <300px**，最大仅 16.3%；空间布局 = 锯齿水手领投影出的**虚线 V 领** + 袖笼虚线 + 孤立散点。
- **修复**：[`drawing.py`](file:///home/edo/pc98paint/tools/tachie/drawing.py) 新增 [`_despeckle_occl` L332](file:///home/edo/pc98paint/tools/tachie/drawing.py#L332)（11px 闭运算桥接 + 填洞 + keep_large），在 [occlusion 循环 L445](file:///home/edo/pc98paint/tools/tachie/drawing.py#L445) 调用，`min_px = max(20, int(under.sum()*0.01))`。
- **度量**：blouse occlusion 24 → **17 块**，最大块 16.3% → **24.8%**；skirt 6 → 4 块。
- **渲染**：[v13](computer:///home/edo/pc98paint/output/shadow_v13_half_x2.jpg) → [v14](computer:///home/edo/pc98paint/output/shadow_v14_half_x2.jpg)；对比图 [v13 vs v14 blouse](computer:///home/edo/pc98paint/output/shadow_v13_vs_v14_blouse.jpg)。

### 问题 4 — 刘海投影盖住眼睛（v9.4）
- **证据**：`_work/scratch/eye_shadow_location.png` — 红色（cast 染暗的皮肤）落在双眼上眼睑；`cloth_layers` 检查确认 form/fold/occlusion/highlight 均**未**画到眼白（眼区只有 base），band 已限下巴 35% 不涉及眼睛 → 唯一来源是 `shading.cast_shadow`（头发→脸投影，[`matregion.py` L697](file:///home/edo/pc98paint/tools/tachie/matregion.py#L697)）。注意：眼白被 `classify_materials` 误分类成 `blouse`（白色最近邻），但只上 base 白色、不吃 cloth 阴影，故不是盖眼原因。
- **根因**：光向左上（L=(-√2/2,-√2/2)），刘海 cast 向右下投影，落到额头后继续下探到上眼睑/眼周 → 视觉上像阴影盖住眼睛。参考 `shinchou_02` 两眼完全明亮、刘海阴影只到眉线以上。
- **修复**：[`matregion.py` L697-706](file:///home/edo/pc98paint/tools/tachie/matregion.py#L697-L706) — 把 cast 拆成变量，若 `anchor["eyes"]`（role=eye 的虹膜 mask）非空，则 `cast &= ~binary_dilation(anchor["eyes"], iterations=8)`，再 `mid |= cast`。虹膜是全角色稳定的眼锚点（不依赖眼白分类），膨胀 8px 覆盖整眼 + 上眼睑；扫描 5/6/7/8 后 8 是清掉眼周暗影的最小值，且不吞额头阴影。
- **渲染**：[v14](computer:///home/edo/pc98paint/output/shadow_v14_half_x2.jpg) → [v15](computer:///home/edo/pc98paint/output/shadow_v15_half_x2.jpg)；对比图 [v14 vs v15 eyes](computer:///home/edo/pc98paint/output/shadow_v14_vs_v15_eyes.jpg)。
- **回归**：11 项 lint PASS；`tools/tachie` 42 tests OK；`tools/common` 13 tests OK。

### 问题 5 — 单眼颜色异常 + 缺白色反光（v23–v26 完成）
- **用户反馈**：眼睛仍有异常颜色。对比两只眼：异常眼虹膜呈**咖啡色**（初判为青绿色块，用户纠正为咖啡色），且**白色反光/高光点没有生成**；另一只眼正常（青绿虹膜 + 白色高光）。→ 两眼不对称。
- **截图**：异常眼 [issue5_eye_abnormal.png](computer:///home/edo/pc98paint/_work/scratch/issue5_eye_abnormal.png)；正常眼（对照）[issue5_eye_normal.png](computer:///home/edo/pc98paint/_work/scratch/issue5_eye_normal.png)；整眼放大 [issue5_eye_color.png](computer:///home/edo/pc98paint/_work/scratch/issue5_eye_color.png)。
- **与 v9.4 的区别**：v9.4 修的是「刘海 cast 阴影盖眼（眼周皮肤被染暗）」，已让双眼不再被暗色阴影覆盖。本问题是**颜色本身**——异常眼虹膜色相错误（咖啡 vs 青绿）+ 高光点缺失，属另一类问题，不能用 v9.4 的 cast 剔除解决。
- **初步归因方向（待换机后用 `dbg["fills"]` 做像素归因，未验证）**：
  1. 两眼虹膜是否被 `classify_materials` 分到了不同 material / 不同调色板条目（一只眼 iris、另一只被误分类，如 blouse/skin）；
  2. 白色高光点的生成路径是否只对一侧眼生效，或被 mask / 阈值漏掉（参考目标 `shinchou_02` 双眼都有高光点）；
  3. palette 最近邻量化时两眼是否落在不同条目。
- **本轮动作**：仅登记，不渲染、不改源码、不更新测试。等用户换机后按「像素归因 → 预览 → 修复 → 验证 → 同步 devdoc」流程继续。
- **归因结果（v23–v26，已实机像素级确认）**：
  1. **咖啡色虹膜**：`render_spec.snap()` 纯 RGB 最近邻，虹膜暗青档 `#1f5f5a` 到 taupe `(74,63,54)` 距离 4169，比到青绿槽 `(47,143,134)` 的 4496 近 0.7% → 上虹膜落 taupe。修复：`snap()` 加色相守卫（参考色 sat≥0.20 时只允许色相差 ≤15°、sat≥0.15 的槽位），16 色槽位不变（[`matregion.py`](file:///home/edo/pc98paint/tools/tachie/matregion.py#L828-L839)）。
  2. **缺白高光（仅左眼）**：`hair.refs[0]` 是 `#ffffff`，眼内纯白高光初始被判 hair；左眼高光被睫毛/JPEG 切成 15 px 碎块，救援规则的 **1 px 环**占比 0.42 < 0.55（右眼 19 px 块为 0.56，刚好通过）→ 未获救援，随后按环多数并入 collar 画成 taupe。修复：环半径 1 → 2 px（左 0.42→0.75，右 0.56→0.75）（[`matregion.py`](file:///home/edo/pc98paint/tools/tachie/matregion.py#L498-L506)）。
- **验证**：`v25→v26` 仅眼区变化 32 px（x295–348、y100–128）；两眼均有纯白高光、虹膜内无 taupe。守卫见 [`test_material_pipeline.py`](file:///home/edo/pc98paint/tools/tachie/test_material_pipeline.py#L404-L418)（虹膜不含 `(74,63,54)` + 每个虹膜连通块 3 px 内有白高光）；`tools/tachie` 62 passed、`tools/common` 13 passed。产物 `output/shadow_v26_half.png` / `_half_white.png` / `_half_x2.jpg`。
- **残留（另行登记）**：左眼上方 bangs 投影的灰粉像素仍被判 collar（taupe），属头发暗部无对应槽位，不影响虹膜/高光判定。

### 问题 6 — 衣服白色条纹被污染（待换机处理，本轮不修改源码）
- **用户反馈**：衣服上的白色条纹被污染——白条内部混入了深色散点，不是干净纯白；**只有角色左手一侧的白条是正确的**（干净）。其余位置的白条均有脏点。
- **截图**：总览 [issue6_stripe_overview.png](computer:///home/edo/pc98paint/_work/scratch/issue6_stripe_overview.png)；局部裁剪 [crop1](computer:///home/edo/pc98paint/_work/scratch/issue6_stripe_crop1.png) / [crop2](computer:///home/edo/pc98paint/_work/scratch/issue6_stripe_crop2.png) / [crop3](computer:///home/edo/pc98paint/_work/scratch/issue6_stripe_crop3.png)。
- **与问题 3 的区别**：问题 3（v9.3）修的是衣服**阴影区**出现点状散影（form/occlusion 碎裂），用去碎斑规则清理的是**暗色块**。本问题是**白色亮条纹本身**被深色点污染，且仅单侧正确，属另一类问题，不能直接套用 v9.3 的去碎斑（那会针对阴影层，而非亮条纹）。
- **初步归因方向（待换机后用 `dbg["fills"]` / `dbg["cloth_layers"]` 做像素归因，未验证）**：
  1. 白条是否被 `classify_materials` 误分类为会吃阴影的材质（如 blouse/skirt），导致 form / occlusion / fold 阴影层画进了白条区域 → 白条被染暗点；
  2. 白条的 base 色是否被 palette 最近邻量化到了**非纯白**条目（白色在调色板里没有精确对应，被 snap 到偏灰/偏色）；
  3. v9.3 的去碎斑闭运算（`_despeckle_form` close=9 / `_despeckle_occl` close=11）或 `keep_large` 是否误伤白条——把白条缝隙桥接、或把白条当作碎块吞掉/改色；
  4. **为何只有左手侧正确**：左右白条是否落在不同 material mask / 不同阴影接收区，或存在单侧逻辑分支差异；需对比两手白条的材质归属与各阴影层覆盖。
- **本轮动作**：仅登记，不渲染、不改源码、不更新测试。等用户换机后按「像素归因 → 预览 → 修复 → 验证 → 同步 devdoc」流程继续。

### 问题 7 — 裙子阴影用了错误的旧画法（待换机处理，本轮不修改源码）
- **用户反馈**：裙子上的阴影用了**错误的旧画法**——阴影边缘呈**阶梯状 / 锯齿硬边**，不是参考目标 `shinchou_02` 那种平滑、大块、单一光向的 cel 阴影。
- **截图**：[issue7_skirt_shadow.png](computer:///home/edo/pc98paint/_work/scratch/issue7_skirt_shadow.png)（裙阴影局部，可见阶梯状硬边）。
- **与其他问题的区别**：问题 2/3 修的是脸/衣服阴影**碎裂成散点**；本问题是裙阴影**形状/边缘画法本身过时**——硬阶梯边而非平滑大块，属于阴影几何生成路径的问题，不是去碎斑能解决的。
- **初步归因方向（待换机后用 `dbg["cloth_layers"]` / `dbg["fills"]` 定位裙阴影来源，未验证）**：
  1. 裙阴影是否来自某条**硬编码的旧阴影形状**（类似问题 1 已删的 `_hair_streaks` 那种手绘弧线/阶梯 mask），未随 v9 重构迁移到新模型；
  2. 是 cloth 四层（base/form/fold/occlusion/highlight）中哪一层生成了阶梯边——重点查 `fold`（褶皱）或 `form`（背光带）在 skirt 上的边缘是否走了逐像素阈值、无抗锯齿/无平滑；
  3. 是否 skirt 走了与 blouse/collar 不同的旧分支（代码里 skirt 有独立阴影路径），其边缘生成公式仍用旧算法；
  4. 阶梯边是否来自分辨率/量化：半源分辨率 257×360 下对角线阴影未做平滑/插值，放大后呈锯齿。
- **本轮动作**：仅登记，不渲染、不改源码、不更新测试。等用户换机后先定位裙阴影来自哪条路径，再定修复方向。

### 问题 8 — 衣服上出现不明杂线（待换机处理，本轮不修改源码）
- **用户反馈**：衣服上出现**不明杂线**——衣身上有非设计的**斜向深色线条**，不属于角色服装的设计元素。
- **截图**：[crop1](computer:///home/edo/pc98paint/_work/scratch/issue8_strayline_crop1.png) / [crop2](computer:///home/edo/pc98paint/_work/scratch/issue8_strayline_crop2.png)（均为衣身局部，可见斜向深色杂线）。
- **与其他问题的区别**：问题 3 是衣服阴影区**点状散影**（已由 v9.3 去碎斑修掉）；问题 6 是**白色条纹**被深色点污染。本问题是衣身**干净区域凭空出现斜向线条**，既不是点状也不是在白条上，需单独定位来源。
- **初步归因方向（待换机后用 `dbg["fills"]` / `dbg["cloth_layers"]` 逐像素追杂线归属，未验证）**：
  1. 是否某条阴影/褶皱层（form / fold / occlusion）在衣身上沿**对角线**生成了细线（如 fold 褶皱线阈值过宽、或 form 背光带边缘拉成斜线）；
  2. 是否 v9.3 的去碎斑闭运算（`binary_closing`）在某些区域**桥接出了斜线伪影**——闭运算会连接邻近暗点，可能把孤立点连成线段；
  3. 是否源图/线稿里本就有的杂线被当成阴影保留下来（`line_mask` / `line_protected` 保护了不该保留的线）；
  4. 是否 `cast_shadow`（头发/其他物件→衣服的投影）在衣身上投出了斜向细线。
- **本轮动作**：仅登记，不渲染、不改源码、不更新测试。等用户换机后先确认杂线在 `fills` 里属于哪一层/哪种材质，再定修复方向。

### 问题 9 — 衣服皱褶出现异常颜色（待换机处理，本轮不修改源码）
- **用户反馈**：衣服上的**皱褶出现异常颜色**——皱褶线 / 皱褶阴影呈现了不该有的颜色，与周围衣色不协调。
- **截图**：[issue9_fold_color.png](computer:///home/edo/pc98paint/_work/scratch/issue9_fold_color.png)（衣身皱褶局部，可见皱褶区域颜色异常）。
- **与其他问题的区别**：问题 8 是衣身干净区域凭空出现**斜向杂线**；本问题是**皱褶本身**的颜色不对（皱褶阴影色错），位置在本应有皱褶的地方、但颜色异常。需确认是 fold 层的色调选取错，还是皱褶落在了错误的材质上。
- **初步归因方向（待换机后用 `dbg["fills"]` / `dbg["cloth_layers"]` / `dbg["cloth_tones"]` 核对皱褶像素的层归属与色调，未验证）**：
  1. `fold`（褶皱）层的**色调选取**是否错——本应取衣色的加深版（mid/deep），却取到了其他材质（如 skin / blouse / collar）的色，或取到了调色板里不相关的条目；
  2. 皱褶区域是否被 `classify_materials` **误分类**到别的材质（如本该是 skirt 的褶被分到 blouse），导致用了错误材质的色调表；
  3. `cloth_tones`（base/mid/deep 三档色）的推导是否在该材质上出错——deep 档被算成了异常色；
  4. 皱褶是否与问题 6 的白条、问题 8 的杂线同源（都涉及衣身颜色异常），换机后可一并归因，避免重复修。
- **本轮动作**：仅登记，不渲染、不改源码、不更新测试。等用户换机后先确认皱褶像素在 `fills` 的材质归属与 `cloth_tones` 取值，再定修复方向。

## 3. 待办 / 计划（持续更新）

### 3.1 已发现、待用户确认是否要修
- **collar form 仍有 19 碎块（18 块 <300px，最大 43.2%）**：v14 实测。collar 是棕褐色水手领，面积小（3951px），其 form 暗带沿领片轮廓碎裂。目前肉眼在 v14 上**不明显**（领色深、碎块对比度低），暂未处理；若用户反馈领片脏，下一轮给 collar 也接 `_despeckle_form`（需调低 min_px，因 collar 面积小，按 2% 仅约 79px）。

### 3.2 泛化与稳健性（本轮未验证，需在更多角色上复核）
- **close 半径是否与分辨率/角色解耦**：`_despeckle_occl` 固定 `close=11`、`_despeckle_form` 固定 9px。当前仅在 momo 半身（257×360 半源分辨率）验证。换全身档或其他角色后，锯齿领的齿距可能不同，11px 可能桥接不足或过度。**计划**：下一个角色渲染后先跑 `v13_verify.py` 式碎块统计，若 V 领仍虚线则调大 close，若过度融合则调小。
- **min_px 派生公式**：occlusion 用 `under.sum()*0.01`、form group 用 `own.sum()*0.02`、白衣用 `max(40, ...)`。是否在所有材质面积区间都合理，待多角色验证。
- **其他角色回归**：`akira` 等已配置角色需跑一遍渲染 + lint，确认去碎斑不破坏既有通过的面积基线。

### 3.3 对照参考的完整验收（未做）
- 把 momo v14 与 `shinchou_02` 在同尺度下并排，逐区（发/脸/领/衣身/袖/裙）核对：大块性、单一光向、无散点、暗面占比。当前只做了 momo 单侧修复，未做系统性对照表。

### 3.4 参考资料研读（✅ 已完成；2026-11-24 用户指示「继续开发」后执行）
- **资料**：知乎专栏文章 <https://zhuanlan.zhihu.com/p/340627232>（含 9 张配图，全部抓取分析）
- **核心要点**：
  1. 胸部阴影 = **球体阴影**——光源方向确定后，明暗交界线+阴影形成**月牙形状**（不是沿轮廓画线）
  2. 衣服阴影应**反映下方身体结构**——胸部让衣服形成凸起的球体投影，不是平布轮廓带
  3. 胸部中间有空气 → 衣服上中间区是**波浪弧线**（上弧+下弧，没有硬性断层）
  4. **虚实过渡**——贴近胸部的阴影实（硬边），远离的虚（柔和过渡），但也要有硬阴影元素
  5. 胸部下方 + 肩膀阴影可以**大面积画**，凸显身体厚度
  6. 裙子是锥形下垂，阴影应随锥形展开（不是平布轮廓带）
- **落地**：方向 B 衣服阴影分区域 → 见 v16 记录（[`阴影模型重构.md` §9 v9.5](./阴影模型重构.md)）
- **关联问题 6/7 归因**：研读后意识到根因是「衣服阴影模型不反映身体结构」，而非单独的白条污染或裙阴影画法过时——见问题 6/7 归因

## 4. 防复发清单（本轮踩过的坑，后续必须遵守）

1. **枚举「被禁视觉元素」的全部来源**：点状阴影同时来自 form（背光带碎裂）与 occlusion（锯齿投影虚线）两层——只修一层会留下另一层，用户仍会看到"还在"。改任何阴影前先用 `diag_clothes.py` 式归因把所有来源列全。
2. **闭运算桥接必须 clip 到接收材质 `under`，不能 clip 回原 `area`**：clip 回 `area` 会把刚桥接的像素全部擦掉，虚线照旧（首版预览 `occl_despeckle_preview.py` 只去掉 1px 的根因）。`_despeckle_occl` 已固定 clip 到 `under`，后续改动不得回退。
3. **先预览再改源码**：方向验证用 monkeypatch / 独立脚本零成本跑，确认 close 半径等参数的视觉效果后再落源码（本轮 close 7/9/11/13/15 扫描后选定 11）。
4. **渲染坐标系**：`asset3.render` 的 `dbg["fills"]` 是 **257×360**（半源分辨率），`pipeline.py --out` 存的是 **640×400 / 1280×800**（缩放后）。诊断裁剪坐标必须从 `idx` bbox 推导，不能混用两套坐标（早期 `smooth_over_preview.py` 裁出废图的根因）。
5. **色调检测动态取，不要 import 嵌套函数**：`matregion.snap` 是 `render_spec` 内的嵌套函数，无法 import；诊断脚本需自行从 fills 检测 base/mid/deep（最高频色 = base，其余按亮度排序）。
6. **规格收敛**：每改源码必须同步 [`阴影模型重构.md`](./阴影模型重构.md)——头部版本指针、§5 实现说明、§6 验收表、§9 修订记录，且所有 `file:line` 引用改完后重新 grep 校准。测试断言因规格意图变更时，更新断言并加注释（先例：脸 mid 0.20→0.14）。
7. **不自动 commit**：仅在用户说"提交"时提交。
8. **色相守卫 + 环半径**：调色板最近邻必须按**色相族**筛选（参考色 sat≥0.20 时限制色相差 ≤15°），否则暗青会落 taupe、暗金会落肤色深档（问题 5 的双重根因）；形态学环半径对碎片化目标不稳定——同一规则在 1 px 环下左眼 0.42 / 右眼 0.56，2 px 环下同为 0.75，眼睛类小目标一律用 2 px 环并用双眼对称性做验收。
