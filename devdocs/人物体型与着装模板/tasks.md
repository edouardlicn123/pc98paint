# 人物体型与着装模板分层 - 实现计划（tasks.md）

依赖图：T1(测量) ∥ T4(schema) → T2(原型) → T3(着装变体)；T2+T4 → T5(解析/自动选择) → T6(prompt)；T4 → T7(layer_edge) → T8(bust 阴影)；T5/T7/T8 → T9(测试)；T6+T8 → T10(端到端)；T1/T2/T3 → T11(文档)。

设计文档：[衣服结构与体型阴影设计](./衣服结构与体型阴影设计.md)（garment_layers 层叠、layer_edge 算法、bust 弧几何映射、body 透传路径）——T7/T8 实现的依据。

## 完成记录（2026-11-23）

全部 11 项已落地并通过回归：

- 测量：`_work/scratch/bust_analysis.json`（24 条）+ `bust_analysis.md`；生成脚本 `_work/scratch/gen_templates.py`。
- 模板：`characters/templates/archetypes/` 24 个、`outfits/` 24 个、`index.json`；测试夹具 `tools/tachie/test_fixtures/templates/`（1 原型 + 2 变体）。
- 代码：`tools/common/template.py`、`schema.py` 扩展、`prompt.py` 参数化、`drawing.py`（layer_edge + bust 弧）、`matregion.py`/`asset3.py`/`pipeline.py` 透传 `body` 与 `resolved_template`。
- 测试：`tools/common/test_template.py`（11 项）、`tools/tachie/test_body_shading.py`（7 项）；全量 tachie 37 项 + common 11 项全部 OK。
- 端到端：momo 自动解析为 `female_highschool_4 / female_highschool_4_sailor`，lint PASS（`white_purity 0.8198`）；显式模板 demo `output/momo_body_demo_half.png` lint PASS（`white_purity 0.8146`）；大胸 demo `momo_full_demo` lint PASS（`0.8080`），平胸 `momo_flat_demo` PASS（`0.8198`）。
- 视觉证据：`_work/scratch/body_shading_demo/collar_layer_edge.png`（领影贴合接缝）、`bust_flat_vs_full.png`（平胸/大胸对比）、`momo_bust_compare.png`（真实立绘胸弧）。
- 文档：`docs/03` §14.1、`docs/06` §2.8、`AGENTS.md` 文档/工具登记与双平台环境说明。
- 复核订正（2026-11-23，用户反馈后）：02 萝莉由 `size=0` 改为 `size=2`（参考图可见胸廓外扩与下胸暗带），发长 `short→long`、瞳色 `magenta→teal`、补黄滚边与脸颊雀斑；同步模板、`docs/03` §14.1、`docs/05`、`docs/06`。
- 新阴影管线（2026-11-23，强制）：渲染配置改为**模板优先**（face/hair 保留实例）；momo 迁移到 `momo / momo_sailor`；白衣三档灰绿 + 大块结构影、头发五档 + 白高光、皮肤三档硬影、角色关闭 Bayer 点阵。重出 `output/momo_newpipeline_half.png`，10 项 lint 全 PASS。
- 阴影误判收口（2026-11-23，用户逐条反馈后）：① 皮肤暗面改为发际投影 + 单连通块轮廓 + 6% 低分位，去掉半脸分位阴影；② 2×2 开闭 + 连通块下限去除下巴点状影；③ 白衣暗带只取外轮廓 1.5%，领下 2px，胸弧面积上限 2%；④ 胸弧按衣身 58% 高度重定位，形成可见 under-boob 线；⑤ 双眼椭圆内暖白与下半身两侧暖白块归回皮肤，修复手部填白；贴脸 3px 白衣保持白色。全部测试 13 + 37 OK。

## Task 1: 实测 24 张参考图的胸围/体型数据
- **Status**: `completed`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - 复用 `_work/scratch/bust_imgs/` 已有的 12 张女性 ruler/grid 图与 `make_bust_ruler.py`，补全缺失的女性参考并新增 12 张男性参考的测量图。
  - 对每张图目读关键坐标（头顶、下巴、肩峰、胸高点、下胸围线），换算为以「头高」为单位的归一化值。
  - 产出 `_work/scratch/bust_analysis.json`（24 条结构化记录）与 `_work/scratch/bust_analysis.md`（方法、分桶阈值、目视备注）。
- **Acceptance Criteria Addressed**: AC-1
- **Test Requirements**:
  - `rule` TR-1.1：`bust_analysis.json` 恰好 24 条记录，每条含 `ref / name / head_height_px / shoulder_ratio / bust.size / bust.center_y_head / bust.separation_ratio / bust.under_boob_y_head`；`bust.size` ∈ {0,1,2,3,4}；男性与平胸参考 `size=0`。证据：`python -c` 加载校验脚本输出。
  - `rule` TR-1.2：`bust_analysis.md` 说明测量方法、归一化公式、size 分桶阈值与每条参考的目视备注。证据：文件存在且含上述小节。
- **Notes**: 男性/平胸不下胸围线时 `under_boob_y_head` 记 `null`。测量脚本放 `_work/scratch/`（调试区），不必登记 AGENTS.md。

## Task 2: 创建模板目录与 24 个原型模板
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 1, Task 4
- **Description**:
  - 新建 `characters/templates/archetypes/`，为 24 张参考图各建一个原型 JSON，`id` 用英文 slug，`name` 用参考图中文名（如「女高中生1」），`ref` 记编号。
  - 每个原型填 `body`（heads/shoulder_ratio/face_width_ratio/bust/torso/pose，数据来自 Task 1）、`face`（脸型/眼型/眉/鼻/嘴/markings，依据 `refs/characters/*_head.png` + `docs/05` 词表）、`hair`（长度/前发/束发/style/color_family/reflection）。
- **Acceptance Criteria Addressed**: AC-2, AC-3, AC-12
- **Test Requirements**:
  - `rule` TR-2.1：`characters/templates/archetypes/` 下恰好 24 个 JSON，每个含 `id/name/ref/body/face/hair`，`body.bust.size` 与 Task 1 一致。证据：`Get-ChildItem` 计数 + 字段遍历脚本。
  - `rule` TR-2.2：全部 24 原型通过 Task 4 的模板 schema 校验，无异常。证据：校验脚本输出。
  - `rubric` TR-2.3：架构清晰度；scale 1-5；anchors 1=信息散落/无名字, 3=有模板但字段不全, 5=24 原型带可读名字、体型/脸型/发型字段齐全且与参考图一致；threshold >= 4；证据：文件检视。
- **Notes**: 词汇严格沿用 AGENTS.md 速查表与 `docs/05`/`docs/06`，不发明新分类。

## Task 3: 创建着装变体模板 + index 注册 + 多变体挂载证明
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 2
- **Description**:
  - 新建 `characters/templates/outfits/`，为每个原型交付参考图里展示的那套装束（校服/工装等）作为一个着装变体 JSON：含 `archetype` 引用、`garment_layers`（层叠顺序，含 over/under/occludes_below）、`materials`、`drawing`（默认用 `derive: layer_edge` 取代手填领影坐标）。
  - 新建 `characters/templates/index.json`：注册表，列出全部原型与变体，含自动匹配关键词（gender / outfit_type / age_group / 名字）。
  - 用一个**测试夹具**（不 shipped 为真实角色）证明同一原型可挂 ≥2 个 outfit（验证校服/常服分离能力），夹具放测试目录。
- **Acceptance Criteria Addressed**: AC-2, AC-3, AC-12
- **Test Requirements**:
  - `rule` TR-3.1：`outfits/` 下 ≥24 个变体 JSON，每个含 `archetype/garment_layers/materials/drawing`，且 `drawing.occlusions` 领影默认用 `derive: layer_edge`。证据：计数 + 字段脚本。
  - `rule` TR-3.2：`index.json` 中至少一个原型关联 ≥2 个 outfit（测试夹具），解析能分别取到两套不同 `garment_layers`。证据：单元测试断言。
  - `rule` TR-3.3：每个变体的 `garment_layers[*].id` 与 `materials[*].id` 交叉引用一致（schema 已校验，此处复核覆盖率 100%）。证据：校验脚本对全部变体无异常。
- **Notes**: 本阶段不虚构常服设计；用户后续提示追加常服时只需新增 outfit 文件 + 改 index，不动原型。

## Task 4: schema 扩展与模板字段校验
- **Status**: `completed`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - `tools/common/schema.py`：新增可选 `template` 字段（引用存在性校验）、`body`（范围：heads 5–7.5、shoulder_ratio 0.8–2.5、bust.size 0–4、torso.lean -0.5–0.5）、`garment_layers`（材质 id 引用一致性）、`occlusions` 的 `derive` 枚举（`layer_edge` 或传统 `path`，二选一）。
  - 新增模板加载/校验函数（如 `load_template(id)` / `validate_template`），供 pipeline 与测试调用。
  - 保证既有 spec（momo/akira/girl_v2）不被新增校验拒绝。
- **Acceptance Criteria Addressed**: AC-3（校验侧）, AC-10
- **Test Requirements**:
  - `rule` TR-4.1：构造非法模板（未知 template 引用 / bust.size=5 / garment_layers 引用不存在材质 / occlusion 同时给 path 与 derive）均抛 `ValueError`。证据：单元测试断言异常。
  - `rule` TR-4.2：`schema.load` 对 `characters/momo/spec.json`、`akira/spec.json`、`girl_v2/spec.json` 无异常。证据：单元测试。
- **Notes**: 与 Task 1 可并行；先定字段契约，Task 2/3 按契约填数据。

## Task 5: pipeline 模板解析（深合并 + 自动选择）
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 2, Task 4
- **Description**:
  - `tools/tachie/pipeline.py`（或新建 `tools/common/template.py`）实现 `resolve_template(spec)`：若 `spec.template` 存在，加载对应 archetype+outfit 深合并（archetype → outfit → instance，instance 优先）；实例已提供的 `drawing / materials / palette / proportions / face / hair` 不被模板覆盖，模板只填补缺失。
  - 无 `template` 时按 `gender + outfit.type + 可选 age_group/名字` 在 `index.json` 确定性打分匹配，选中 id 写入渲染 report。
- **Acceptance Criteria Addressed**: AC-4, AC-5
- **Test Requirements**:
  - `rule` TR-5.1：构造实例（设 template，且 `proportions.heads` 与模板不同）→ effective `proportions.heads` 为实例值，`body.bust`（实例未给）为模板值。证据：单元测试断言。
  - `rule` TR-5.2：对 ≥3 组无 template 的关键词输入（如 female+sailor / male+blazer / female+office），断言各选中精确模板 id，且重复运行 id 相同。证据：单元测试。
  - `rule` TR-5.3：report JSON 含 `resolved_template` 字段（或等价）。证据：端到端渲染 report 检视。
- **Notes**: 深合并用字典递归覆盖；列表字段（materials/folds）整体替换不拼接，避免重复。

## Task 6: prompt.py 体型 token 参数化
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 5
- **Description**:
  - `tools/common/prompt.py`：`build()` 从 effective（合并后）`body`/`face`/`hair` 取头身、肩宽、发型等 token；从 `STYLE_POS` 移除硬编码的 `"6-head proportions, narrow shoulders"`。
  - `STYLE_POS` 保留与体型无关的风格描述（PC-98、cel-shaded、1px 线等）。
- **Acceptance Criteria Addressed**: AC-6
- **Test Requirements**:
  - `rule` TR-6.1：`Select-String "6-head proportions|narrow shoulders" tools/common/prompt.py` 在 `STYLE_POS` 定义内无匹配。证据：grep 输出为空。
  - `rule` TR-6.2：给定 effective body（heads=6.5, shoulder_ratio=1.4），`prompt.build` 输出含 `6.5 head` 与相应肩宽描述。证据：单元测试断言子串。
- **Notes**: 不改变 prompt 的机位/表情/高光硬约束。

## Task 7: drawing.py 结构派生遮挡 derive=layer_edge
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 4
- **Description**:
  - `build_cloth_layers` 的 occlusion 分支新增 `derive == "layer_edge"`：计算 `over` 与 `under` 材质的真实边界（`_material_boundaries` 已存在），取 under 侧邻接像素，向 under 内部膨胀 `width`，裁剪到 `under` 掩码内 → 紧贴 over 下沿的阴影带。
  - 保留 `path` 分支与 `binary_dilation(over)` 旧分支（当既无 path 也无 derive 时）以向后兼容 momo 现有配置。
- **Acceptance Criteria Addressed**: AC-7
- **Test Requirements**:
  - `rule` TR-7.1：构造左右相邻的 over/under 合成掩码 + `derive=layer_edge,width=2`，断言生成的 occlusion 像素全部 ∈ under，且每个阴影像素到 over/under 边界的距离 ≤ width+1。证据：单元测试像素集合距离断言。
  - `rule` TR-7.2：对 momo 现有 `path` 型 occlusion 配置，渲染结果与改造前一致（回归）。证据：既有 `test_drawing_pipeline.py` 仍通过 + momo 局部像素 diff。
- **Notes**: 边界距离用 `scipy.ndimage.distance_transform_edt` 对 over 掩码计算，取 under 内距离 ≤ width 的像素。算法细节见[设计文档 §4](./衣服结构与体型阴影设计.md)。

## Task 8: drawing.py 胸围驱动衣物阴影（under-boob arc + lean 偏移）
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 7
- **Description**:
  - `build_cloth_layers` 接收 effective `body`（pipeline 透传）：当 `bust.size >= 2`，在白衣（role=white）材质掩码上，按 bust 的 `center_y` / `separation` / `size` 派生一条 under-boob 弧形 occlusion 带（宽度随 size 增大）；`size == 0` 不产生胸部暗化。
  - 弧的水平中心随 `torso.lean` 偏移；弧的纵向位置按归一化 bust.center_y 映射到白衣材质 bbox。
- **Acceptance Criteria Addressed**: AC-8, AC-13
- **Test Requirements**:
  - `rule` TR-8.1：同一白衣掩码 + 相同光源，分别传 `bust.size=0` 与 `bust.size=3`，断言 size=3 在 bust 几何范围内产生 size=0 没有的弧形阴影像素，差异像素数 > 50（半身尺度）。证据：单元测试像素 diff。
  - `rule` TR-8.2：`torso.lean` 从 0 变到 0.3 时，under-boob 弧的水平质心位移 > 0 且方向与 lean 一致。证据：单元测试质心坐标断言。
- **Notes**: bust 几何映射用白衣材质 bbox 的归一化坐标（与现有 folds/occlusion 的 `_points` 同体系），保证跨角色/姿势自适应。弧参数、size 档位触发、torso.lean 偏移见[设计文档 §5](./衣服结构与体型阴影设计.md)。

## Task 9: 全量单元测试回归
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 5, Task 7, Task 8
- **Description**:
  - 把 Task 4/5/7/8 的 TR 测试落到 `tools/tachie/test_*.py` 与 `tools/common/` 测试（如不存在则新建），与实现耦合提交。
  - 运行全量测试，修复回归，确保既有 30 测试 + 新增全部通过。
- **Acceptance Criteria Addressed**: AC-4, AC-5, AC-7, AC-8, AC-10
- **Test Requirements**:
  - `rule` TR-9.1：`python -m unittest discover -s tools/tachie -p "test_*.py" -v` 与 common 相关测试全部 pass，无 fail/error。证据：测试运行输出 pass 计数。
- **Notes**: 各实现任务的 TR 已在本任务汇总验证；实现时同步写测试，本任务做最终全量回归。

## Task 10: 端到端验证（momo 回归 + 大胸/平胸对比）
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 6, Task 8
- **Description**:
  - momo 用改造后管线渲染半身，与 `output/momo_layered_candidate_half.png` 做像素 diff，确认在容差内、lint 通过、色板不变。
  - 选一个大胸原型（成熟女性1 或 人妻职业女性）与一个平胸原型（萝莉 或 男高中生1），用各自模板渲染（可用既有或临时 source），输出对比图到 `_work/scratch/`，目视验证领影贴合 + 胸围阴影差异。
- **Acceptance Criteria Addressed**: AC-9, AC-11, AC-13
- **Test Requirements**:
  - `rule` TR-10.1：momo 渲染成品与基线像素差 ≤ 既有面积容差（0.35 相对面积对应像素阈值），且不新增 lint 失败项。证据：渲染 report + 像素 diff 数据。
  - `rule` TR-10.2：momo 与大胸/平胸三例 lint 均通过。证据：各例 `*_lint.json`。
  - `rubric` TR-10.3：领影视觉（AC-11）；scale 1-5；anchors 1=仍飘在领中部, 3=大致沿缘但间断, 5=紧贴领下沿宽度均匀；threshold >= 4；证据：`_work/scratch/<name>_drawing/cloth_occlusion.png` 叠加 `material_idx.png` 目视。
  - `rubric` TR-10.4：胸围表达力（AC-13）；scale 1-5；anchors 1=无差异, 3=有差异但位置/形状不对, 5=大胸有清晰 under-boob 弧、平胸无胸部暗化且与参考图一致；threshold >= 4；证据：大胸 vs 平胸渲染对比图 + 参考图并置。
- **Notes**: 若大胸/平胸例无现成高清 source，用 `--drawing-debug` 输出的 cloth 层叠加图做结构验证即可，不必强行端到端出成品；但 momo 必须端到端。

## Task 11: 文档更新
- **Status**: `completed`
- **Priority**: low
- **Depends On**: Task 1, Task 2, Task 3
- **Description**:
  - `docs/03_人物的做法.md` 新增「胸围数据」小节，纳入 Task 1 的 24 原型胸围表与分桶规则（接在 §14 三轴模型之后）。
  - `docs/06_服装设计.md` 新增「三层着装模板」小节，说明 archetype/outfit/instance 分离与 `garment_layers` 驱动的结构派生阴影。
  - 若本阶段新增了 `tools/` 下的常驻脚本（如 `template.py`），在 AGENTS.md 工具注册表登记。
- **Acceptance Criteria Addressed**: AC-12（文档侧）
- **Test Requirements**:
  - `rule` TR-11.1：`docs/03` 含胸围小节且有 24 原型数据表。证据：文件检视。
  - `rule` TR-11.2：`docs/06` 含三层着装模板说明。证据：文件检视。
- **Notes**: 不改动文档既有结论，只新增小节。

## Addendum: 阴影复核（2026-11-23，v5 → v8）
- **Status**: `completed`
- **修复项**：
  1. 脸部连通块改为以**膨胀后的虹膜**为锚（虹膜是独立材质，`skin ∩ iris` 恒为空，旧逻辑永远选不到脸），额带/下颌带真正落位。
  2. `white_seed` 之后二次执行面部椭圆回收，清除鼻/颊高光被误染成白衣留下的白斑。
  3. 白衣中/深面参数改为 sigma 8 / p30 / p8 / min_px 300 / 9px 开闭 + 填洞，去掉碎斑。
  4. 胸下暗带改为**受光背面单侧月牙**（厚中薄端，tone 1，面积上限 2.5%），不再出现左右两条“微笑”弧。
  5. 线层清理只作用于布料内部（<12px、8 邻域、邻接长线豁免）；头发发丝保留，避免误删合法发丝。
- **验证**：`pipeline.py` 11 项 lint 全 PASS；`tools/tachie` 37 tests OK；`tools/common` 13 tests OK；baseline 更新为 skin 4806 / hair 23475 / blouse 15715 / collar 3421 / skirt 9358 / bow 2532 / iris 161（tolerance 0.35）。

## Addendum: 阴影模型重构（v9，2026-11-23）
- **Status**: `completed`
- **内容**：新增 `tools/tachie/shading.py`（固定左上光向、骨架传播局部内切半径、背光带、投影带），替换 `matregion` 的源图亮度分位/发块 bbox 暗带/发际横带，替换 `drawing` 的 `rim_shadow` 与白衣残影归并；`layer_edge` 先腐蚀 `over` 跳过蕾丝齿尖；分类器增加下半身孤立发色岛回收与发上白点回收；`skirt` refs 改为色板三色；`white_purity` 统计排除肤色基色。详见[阴影模型重构](./阴影模型重构.md)。
- **验证**：momo 半身 11 项 lint PASS；`tools/tachie` 42 tests OK（新增 `test_shadow_model.py` 5 条 + momo 色调分布断言）；`tools/common` 13 tests OK；脸中影 27.4%、头发 base 48.9%/高光 3.7%、白衣 mid 21.1%/deep 5.7%、裙 mid 17.3%/deep 13.2%。
