# 人物体型与着装模板分层 - 产品需求文档（PRD）

## Overview
- **Summary**：为 PC-98 立绘管线引入「身体体型 + 着装结构」驱动的阴影系统，并把 24 个参考原型固化为可复用的 JSON 模板（原型 → 着装变体 → 角色实例 三层架构）。管线在 prompt 未强调细节时自动套用合适的基础角色数据，再叠加实例微调，最终让上衣/裙子/皮肤的遮挡阴影与胸围大小都能表达身体形态。
- **Purpose**：解决上一阶段遗留的两个核心问题——(1) 衣物阴影与体型无关（`form` 暗带只是材质右半边，699px 变化肉眼几乎不可见）；(2) 手填归一化坐标的 `occlusion` 落错位置（领影飘在 V 字中间而非领下沿）。同时补齐 `docs/03` 缺失的胸围数据，并让 prompt 不再硬编码体型。
- **Target Users**：项目维护者（在 `characters/` 下配置新角色的人）与最终立绘消费者。

## Related Documents
- [衣服结构与体型阴影设计](./衣服结构与体型阴影设计.md)：FR-2/FR-4/FR-8/FR-9 的详细设计——`garment_layers` 衣衣层叠遮挡链、`derive: layer_edge` 算法、bust→under-boob 弧的几何映射与 body 透传路径。

## Goals
- 从 `refs/proportions/` 的 24 张参考图实测胸围/体型数据（B：校准证据），固化为静态可复用模板（A：避免运行时最近邻漂移）。
- 建立清晰的人物类型架构：**原型（archetype，带名字）→ 着装变体（outfit variant）→ 角色实例（character instance）** 三层。
- 原型层记录**体型特征、脸型眼睛设计、发型设计**（同原型共享）；**校服与常服在「着装变体」层严格分开**。
- 管线自动选择并套用基础角色数据，再叠加实例 prompt 微调。
- 服装结构与身体分层驱动阴影：上衣→裙子→皮肤的遮挡派生；胸围大小改变衣物阴影。

## Non-Goals
- 本阶段**不新增参考图之外的常服变体**（用户后续提示再加）；只把架构做成可分离，并交付参考图里现有的装束。
- 不改 `material_idx` 分类、已审定 `palette.json` 槽位/颜色、16 色量化/抖动、alpha 通道、裁切与 640×400 构图。
- 不做运行时对参考图的最近邻检索；所有体型/着装数据静态化为 JSON。
- 不覆盖已审定的 momo 成品、面积基线与色板。
- `refs/proportions/` 的 extras（shinchou_25/27/31）暂不纳入，后续可追加。
- 不新增高清源图的 AI 重生成；验证用既有源图或合成掩码。

## Background & Context
- 上一阶段已完成线稿/布料五层架构（`tools/tachie/drawing.py` 的 `LineLayers` / `ClothLayers`）与 momo 配置，30 个测试通过，momo 端到端通过 lint 且色板不变。
- 像素量化证据：momo 配置前后仅 699px 变化，其中 406px 在 fold 区且颜色只变一档；`form`（右侧轮廓暗带）主导衣物阴影且与体型无关 → 阴影不表达身体形态。
- 领影偏移证据：`_work/scratch/collar_occ.jpg` 的紫色 occlusion 线落在领 V 字中间，而非沿领下沿；根因是 `occlusion.path` 手填归一化坐标猜位置，换角色/姿势必错。
- 现状空白：所有 spec 的 `proportions` 只有 `heads / head_width_ratio / eye_width_ratio / nose_px / mouth_px`（全是头脸）；无 `body / bust / torso / shoulder / pose` 字段；`akira` 有 `face_planes/profile` 但仅限脸；`tools/common/prompt.py` 的 `STYLE_POS` 硬编码 `"6-head proportions, narrow shoulders"`；`drawing.rim_shadow` 固定取材质右半、k=宽×2%，与体型/胸围/姿势完全无关。
- `docs/03_人物的做法.md` §14 已有「年龄 × 性别 × 体型」三轴比例模型（少女肩/头 1.09–1.49、成年 1.57–2.05，1.5 处硬断；矮小只压腿不压躯干等），但**无任何胸围数据**——这是本阶段要补的明确缺口。
- 24 张参考图：`shinchou_01`–`24`，`refs/characters/` 有每张的 `_head.png` / `_body.png` 拆图。
- 被中断的子代理已在 `_work/scratch/bust_imgs/` 留下 12 张女性参考的 ruler/grid 图与 `make_bust_ruler.py`（含 HH 头高、FACE 脸宽比），但**无最终 `bust_analysis.*`**，需补全 24 张并产出结论。
- 用户已确认的口径：(1) 24 张参考图 = 24 个独立原型，每个带名字；(2) 常服变体本阶段只做参考图能提供的内容，后续再加。

## Functional Requirements

- **FR-1（胸围实测）**：对 `refs/proportions/` 全部 24 张参考图实测体型/胸围，产出 `_work/scratch/bust_analysis.json` 与 `bust_analysis.md`。数据以「头高」为归一化单位（分辨率无关），至少含：头高、肩宽/头高比、胸高点 y（距头顶的头高倍数，`1.0`=颈线）、两胸间距/白衣 bbox 宽度比、下胸围线 y、胸围档位 `size`（0=平胸/男性，1=小，2=中，3=大，4=丰满）；男性/平胸参考显式标记 `size=0` 且不下胸围线。
- **FR-2（三层模板架构）**：在 `characters/templates/` 下建立三层 JSON：原型（`archetypes/`）、着装变体（`outfits/`）、索引（`index.json`）。原型与着装变体**分离存储**，同一原型可挂多个着装变体；校服与常服是同一原型下的两个不同着装变体。
- **FR-3（原型记录体型/脸型/发型）**：每个原型 JSON 带 `name`（如「女高中生1」）、`ref`（参考图编号），并记录：`body`（heads、shoulder_ratio、face_width_ratio、bust、torso、pose）、`face`（脸型、眼型/大小、眉、鼻、嘴、markings）、`hair`（长度、前发、束发、style、color_family、reflection）。词汇沿用 `docs/05`/`docs/06` 与 AGENTS.md 速查表，不自由发明。
- **FR-4（着装变体记录服装结构）**：每个着装变体 JSON 记录 `garment_layers`（层叠顺序：如 undershirt→collar→skirt，含 `over`/`under`/`occludes_below`）、`materials`、`drawing`（folds / occlusions / surfaces）。校服与常服分属不同变体文件。
- **FR-5（实例引用与覆盖）**：`characters/<name>/spec.json` 可通过 `template` 字段引用 `{archetype, outfit}`，管线深合并 原型 → 着装变体 → 实例，**实例字段优先**；实例已提供的 `drawing / materials / palette / proportions` 不被模板覆盖，模板只填补缺失字段。
- **FR-6（自动选择）**：当实例未指定 `template` 时，管线按 `gender` + `outfit.type` + 可选 `age_group`/名字关键词在 `index.json` 中确定性匹配最合适的原型+着装变体，并在 report 中记录选中的模板 id；匹配可复现（同 spec 永远选同模板）。
- **FR-7（prompt 体型参数化）**：`tools/common/prompt.py` 从合并后的 effective body/face/hair 取体型 token；`STYLE_POS` 不再硬编码头身数与肩宽描述。
- **FR-8（结构派生遮挡）**：`drawing` 的 `occlusions` 新增 `derive: "layer_edge"` 模式——取 `over` 材质朝向 `under` 的真实边界，向 `under` 侧膨胀 `width` 得到紧贴真实边缘的阴影带，取代手填坐标；保留既有 `path` 模式以向后兼容。
- **FR-9（胸围驱动衣物阴影）**：`build_cloth_layers` 依据 effective `body.bust`：`size==0` 不在白衣/布料上产生胸部暗化；`size>=2` 自动在白衣材质上派生一条 under-boob 弧形 occlusion（位置/宽度由 bust 的 center_y / separation / size 决定），并随 `torso.lean` 水平偏移。
- **FR-10（向后兼容）**：未指定 `template` 的既有 spec（如 momo）经自动选择与合并后，渲染结果与当前基线像素差在既有容差内（`drawing / materials / palette` 不变）；现有 30 个测试继续通过。
- **FR-11（校验与 lint）**：`schema.py` 校验新增可选字段（template 引用存在性、body 范围、bust 档位、garment_layers 材质引用、occlusion derive 模式），非法配置拒绝；端到端 lint 通过。

## Non-Functional Requirements
- **NFR-1（确定性）**：同一 spec + 同一 source → 完全相同输出；模板解析结果写入 report JSON。
- **NFR-2（无运行时检索漂移）**：所有体型/着装数据为静态 JSON，渲染时不读参考图做最近邻。
- **NFR-3（性能）**：模板解析 + 结构派生遮挡给单张半身渲染增加的时间 < 10%。
- **NFR-4（代码规范）**：注释中文；新增脚本放 `tools/` 对应子目录并在 AGENTS.md 登记；路径用 `Path(__file__)` 相对定位，不写绝对盘符（scratch 调试脚本除外）。
- **NFR-5（可测）**：模板合并、自动选择、layer_edge 像素带、bust 0 vs ≥2 阴影差异均有单元测试；不依赖外部网络。

## Constraints
- **Technical**：不改 `material_idx` 分类、色板槽位/颜色、16 色量化与抖动、alpha、裁切、640×400 构图；默认单张半身·平视·无表情；正式产物写 `output/`，调试写 `_work/scratch/`。
- **Business**：不覆盖已审定 momo 成品/面积基线/色板；用户未确认前不改既定管线设计。
- **Dependencies**：`numpy / pillow / scipy`（已有）；胸围测量需人工目视读 ruler 叠加图坐标，无法纯自动（参考图无关键点标注）。

## Assumptions
- 24 张参考图 = 24 个独立原型，每个带 `name`（沿用参考图文件名里的中文名）。
- 每个原型本阶段只交付参考图里展示的那套装束作为着装变体；常服变体由用户后续提示追加，架构已支持。
- 胸围档位 `size` 由「两胸间距/肩宽比 + 目视体积」分桶校准，0–4 整数档；男性/萝莉扁平者为 0。
- 原型的 `face` / `hair` 依据对应 `refs/characters/*_head.png` 与 `docs/05` 词表填写，不重新发明分类。
- 既有 momo 的 `drawing` 手填配置在过渡期保留；新模板默认用 `derive: layer_edge`，momo 是否迁移由用户后续决定（本阶段不强制迁移，保证回归）。

## Acceptance Criteria

### AC-1：24 张参考胸围实测完成
- **Type**: `rule`
- **Given**: `refs/proportions/` 有 shinchou_01–24 共 24 张
- **When**: 执行测量流程
- **Then**: `_work/scratch/bust_analysis.json` 含 24 条记录，每条有 `ref / name / head_height_px / shoulder_ratio / bust.size / bust.center_y_head / bust.separation_ratio / bust.under_boob_y_head`；男性与平胸者 `bust.size=0`
- **Pass Condition**: 24 条记录齐全，字段无缺，size 取值在 0–4
- **Evidence**: `bust_analysis.json` 存在且 `python -c` 校验 24 条记录字段完整；`bust_analysis.md` 说明方法与分桶

### AC-2：三层模板目录与分离存储
- **Type**: `rule`
- **Given**: 无 `characters/templates/`
- **When**: 模板创建完成
- **Then**: 存在 `characters/templates/archetypes/`（24 个原型 JSON）、`characters/templates/outfits/`（≥24 个着装变体 JSON）、`characters/templates/index.json`（注册表，含自动匹配关键词）
- **Pass Condition**: archetype 与 outfit 在不同文件；至少一个原型在 index 中关联 ≥2 个 outfit（证明可分离，可用测试夹具，不必是 shipped 角色）
- **Evidence**: `Get-ChildItem` 计数 + index.json 关联校验脚本

### AC-3：原型与着装变体字段完整
- **Type**: `rule`
- **Given**: 模板已创建
- **When**: 加载任一原型与对应着装变体
- **Then**: 原型含 `name / ref / body / face / hair`；着装变体含 `archetype / garment_layers / materials / drawing`；`garment_layers` 与 `materials` 的 id 互相引用一致
- **Pass Condition**: 全部 24 原型 + 其变体通过 schema 校验
- **Evidence**: `schema.load`/模板校验对全部模板无异常

### AC-4：实例引用模板且实例优先合并
- **Type**: `rule`
- **Given**: 一个实例 spec 设了 `template` 且在 `proportions.heads` 与模板不同
- **When**: `resolve_template(spec)` 合并
- **Then**: effective `proportions.heads` 取实例值；实例未提供的 `body.bust` 取模板值
- **Pass Condition**: 实例字段覆盖模板，模板填补缺失
- **Evidence**: 单元测试断言合并后的字段值

### AC-5：无模板时自动选择确定性匹配
- **Type**: `rule`
- **Given**: 实例不指定 `template`，但有 `gender=female` + `outfit.type=sailor`
- **When**: `resolve_template` 运行
- **Then**: 选中一个 female+sailor 原型+变体，并写入 report；重复运行选中 id 相同
- **Pass Condition**: 多组关键词输入各断言选中 id 正确且稳定
- **Evidence**: 单元测试对 ≥3 组关键词断言精确选中 id

### AC-6：prompt 体型 token 参数化
- **Type**: `rule`
- **Given**: effective body 有 `heads` 与 `shoulder_ratio`
- **When**: `prompt.build(spec)`
- **Then**: 正向提示词含 effective 的头身与肩宽描述；`STYLE_POS` 源码不再出现 `"6-head proportions"` 或 `"narrow shoulders"` 硬编码
- **Pass Condition**: grep `STYLE_POS` 无硬编码；输出 prompt 含 effective 数值
- **Evidence**: `Select-String` 源码检查 + prompt 输出断言

### AC-7：layer_edge 遮挡紧贴真实材质边界
- **Type**: `rule`
- **Given**: 两个相邻材质 over/under 的合成掩码，配置 `derive=layer_edge, width=2`
- **When**: `build_cloth_layers` 生成 occlusion
- **Then**: 阴影带像素全部位于 under 材质内、且距 over/under 边界 ≤ width+1 px（不飘离到材质中部）
- **Pass Condition**: 像素带在边界侧、距离满足
- **Evidence**: 单元测试构造掩码，断言阴影像素集合到边界的最大距离

### AC-8：胸围档位改变胸部阴影
- **Type**: `rule`
- **Given**: 同一白衣材质掩码，分别用 `bust.size=0` 与 `bust.size=3` 渲染
- **When**: 对比 form+occlusion 结果
- **Then**: size=3 在胸下沿区域产生 size=0 没有的弧形阴影像素；差异像素数 > 阈值
- **Pass Condition**: 两结果胸下区域像素差 > 0 且位于 bust 几何范围
- **Evidence**: 单元测试像素 diff 断言

### AC-9：momo 向后兼容（像素回归）
- **Type**: `rule`
- **Given**: momo 现有 spec（无 template）+ 既有 source 与面积基线
- **When**: 用改造后管线渲染半身
- **Then**: 成品与当前基线像素差 ≤ 既有容差；lint 通过；色板不变
- **Pass Condition**: 像素差在容差内、lint 无新增失败项
- **Evidence**: 渲染命令输出 + 与 `output/momo_layered_candidate_half.png` 像素 diff 数据

### AC-10：全量测试通过
- **Type**: `rule`
- **Given**: 实现完成
- **When**: `python -m unittest discover -s tools/tachie -p "test_*.py" -v`（及 common 相关测试）
- **Then**: 既有 30 测试 + 新增测试全部通过
- **Pass Condition**: 无失败、无错误
- **Evidence**: 测试运行输出（pass 计数）

### AC-11：结构派生领影视觉正确（rubric）
- **Type**: `rubric`
- **Dimension**: 领下沿遮挡阴影是否贴合领子真实下边缘（而非飘在 V 字中间）
- **Scale**: 1-5
- **Anchors**: 1 = 阴影仍飘在领中部/错位；3 = 大致沿领缘但有间断；5 = 阴影带紧贴领下沿、宽度均匀、过渡自然
- **Pass Threshold**: >= 4
- **Evidence**: `_work/scratch/<name>_drawing/cloth_occlusion.png` 与 `material_idx.png` 叠加目视

### AC-12：人物类型架构清晰度（rubric）
- **Type**: `rubric`
- **Dimension**: 能否清晰查到「女子高中生1·校服」这类条目，并看到其体型/脸型眼睛/发型/穿着，且校服与常服在架构上分离
- **Scale**: 1-5
- **Anchors**: 1 = 信息散落在 spec 无法查；3 = 有模板但字段不全或校服常服未分离；5 = 三层结构清晰、名字可读、字段齐全、校服常服可分别挂载
- **Pass Threshold**: >= 4
- **Evidence**: `characters/templates/` 文件与 index 检视

### AC-13：胸围驱动阴影的表达力（rubric）
- **Type**: `rubric`
- **Dimension**: 大胸原型 vs 平胸原型的衣物阴影是否能体现体型差异，并与参考图观感一致
- **Scale**: 1-5
- **Anchors**: 1 = 两者阴影无差异；3 = 有差异但位置/形状不对；5 = 大胸有清晰 under-boob 弧、平胸无胸部暗化，且与参考图一致
- **Pass Threshold**: >= 4
- **Evidence**: 大胸例（如成熟女性1/人妻职业女性）与平胸例（萝莉/男高中生）渲染对比图 + 参考图并置

## Open Questions
- [ ] 胸围档位 `size` 的分桶阈值（两胸间距/肩宽比的切点）需在测量后用实测分布确定，初步设 0/1/2/3/4 五档，最终阈值记录在 `bust_analysis.md`。
- [ ] 原型 `face`/`hair` 的细粒度取值（如「女高中生1」眼型究竟是杏还是圆）以 `refs/characters/*_head.png` 目视为准，若有歧义在 `index.json` 备注，不阻塞主流程。
- [ ] 常服变体的具体设计与覆盖范围由用户后续提示确定，本阶段只保证架构可挂载。
