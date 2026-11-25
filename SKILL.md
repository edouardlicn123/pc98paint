# 管线C：插画 → PC-98 立绘（项目即 Skill）

> 本文件是整个项目的入口说明。**管线C 是默认管线**：用户用自然语言提需求，agent 按本文七步执行，默认产出 HD 角色图；**PC-98 用图仅在用户明确要求时产出（2026-11-25 起）**。
> 画风约束见 `docs/11_画风规范_90年代赛璐璐.md`；PC-98 规格见 `docs/03_人物的做法.md`。

## 何时使用

- 「画一个 / 出一个 XX 角色（立绘、三视图、特写、全身图）」
- 「把这个角色改成 PC-98 风格」「出一套能进游戏的立绘」
- 需要**在模板库基础上派生新角色**（体型、服装、发色等小幅调整）

不适用：场景图、UI、多人构图、动态姿势。

## 输入（C1 由 agent 完成）

把用户的话解析成结构化 brief（写进 `output/<slug>/brief.json`）：

```json
{
  "name": "粉发水手服女高中生",
  "template": {"archetype": "momo", "outfit": "momo_sailor"},
  "gender": "female",
  "age_group": "teen",
  "outfit_type": "sailor",
  "proportions": {"heads": 6.2},
  "hair": {"color": "#f1969b", "length": "waist", "style": "wavy"},
  "face": {"iris": "#317242"},
  "colors": {
    "hair": ["#f6d9db", "#f1969b", "#c16b70", "#854145", "#6a3138"],
    "blouse": ["#fbefdf", "#ded2c2", "#b3a797"],
    "collar": ["#7b544a", "#654137", "#4c322b"],
    "skirt":  ["#9f6d59", "#8a5c46", "#5f3b2c"],
    "bow":    ["#fcb378", "#e2a067"]
  },
  "overrides": ["不要毛衣质感", "裙长膝上"]
}
```

- `template` 可选：固定原型/服装（不写则由 `auto_select` 按 gender/outfit_type/age_group/keywords 打分选最高）。**某种服装缺某种材质时（如多数 outfit 没有 `collar`），必须用 `template` 指定带该材质的 outfit（如 `momo_sailor`）。**
- `colors` 按 material `id` 覆盖 `refs`；id 不存在时会尝试别名（`blouse↔top`、`skirt↔bottom`、`collar↔inner`、`bow↔accent`）；只给 1 个颜色时自动派生 3 档（受光提亮降饱和、中间调=原色、暗档降明度×0.55+饱和×1.18+色相 -18°）。
- `overrides` 是必须生效的改动，写 prompt 时逐条并入负面块或角色描述。

字段缺省时交给模板库决定；`overrides` 是必须在该角色上生效的改动。

## 七步流程

| 步 | 动作 | 命令 / 载体 |
|---|---|---|
| C0 | **出图前必读** `STYLE_KEYWORDS.md`（全局强制画风，单一事实源；泳装时还用其 `SWIM_REQUIRED` 条款） | 根目录文件 |
| C1 | 需求 → `brief.json` | agent 直接写文件 |
| C2 | 模板匹配（26 原型 + 26 服装，按 gender/outfit_type/age_group/keywords 打分） | `python -m tools.pipeline_c brief --brief output/<slug>/brief.json --slug <slug> --out characters/<slug>/spec.json` |
| C3 | 合成角色 spec（含按 `colors` 重算材质 refs）并落盘 | 同上，打印 `COLORS: applied=… derived=… ignored=…` |
| C4 | 组装英文 prompt（STYLE + 构图块 + 角色描述 + 负面；画风前缀由 `tools/common/style.py` 读取 `STYLE_KEYWORDS.md` 强制前置） | `python -m tools.pipeline_c prompt --spec characters/<slug>/spec.json --kind tachie` |
| C5 | **IDE 出图**（agent 调生成通道，只出三视图 `sheet`；立绘不重新生成） | agent 工具调用，产物落 `output/<slug>/hd_sheet.png` |
| C5.5 | **立绘唯一来源**：从三视图正面视图裁出（确定性，无人设漂移；默认 `--cut 0.50` 到胯，到膝用 `0.76`）。**必须带 `--spec`**：出图后先在三视图正面视图上重画鼻子（1.5 倍左半实心菱形）与嘴巴（以原嘴线两端为锚点、中间向下弧形下压的单条细微笑弧线）（2026-11-25 起强制） | `python -m tools.pipeline_c.from_sheet --sheet output/<slug>/hd_sheet.jpg --out output/<slug>/_front_half.png --crop half --spec characters/<slug>/spec.json --nose-scale 1.5 --nose-half left` |
| C6 | **可选**：转 PC-98 用图（640×400 索引色，index 0 透明）。**2026-11-25 起默认跳过**，仅用户明确要求 PC-98 / 640×400 / 进游戏素材时执行 | `python -m tools.pipeline_c convert --spec ... --src output/<slug>/_front_half.png --mode half --out output/<slug>/<slug>.png` |
| C7 | **可选**：PC-98 成品验收（仅在执行 C6 后） | `python -m tools.pipeline_c verify --png pc98_tac.png` |

`kind` 取 `sheet`（三视图）/`tachie`（立绘）/`closeup`（特写）/`full`（全身图），与 `docs/11` §2 的画幅、色阶参数一一对应。

### C5 的画幅约定

| kind | image_size | 说明 |
|---|---|---|
| sheet | 2560x1440 | 正/侧/背并列 |
| tachie | 1440x2560 | 站姿，膝上或全身 |
| closeup | 1680x2240 | 胸像，脸占 40% |
| full | 1440x2560 | 全身含脚 |

## 产物结构

```
characters/<slug>/spec.json                 # 角色定义（可复用、可再派生）
output/<slug>/
  brief.json                                # 需求快照
  spec.snapshot.json                        # 本次使用的 spec 副本
  prompt_<kind>.txt                         # 实际送去生成的 prompt（必存）
  hd_<kind>.png                             # IDE 生成图
  pc98_tac.png                              # 转换结果（基名必须 ≤8 字符）
```

prompt 必须落盘：IDE 生成不可复现，唯一能追溯的就是当时那段文字与 spec 快照。

## 能力边界（必须向用户说明）

1. IDE 生成通道**只吃文字**，不吃参考图 → 同一角色跨图不能保证完全一致。
2. 画风只能**近似**目标样图，不能像素级复刻；要锁画风需 img2img / IP-Adapter，当前通道不支持。
3. 不可锁 seed，同一 prompt 两次结果不同。
4. PC-98 转换（C6）是确定性脚本，可复现；HD 生成不是。

## 验收

- 画风：`docs/11` §5 的七条自检。
- PC-98 侧：尺寸 640×400、色数 ≤256（16 色期 ≤16）、index 0 透明、文件名 8.3 安全、不写入 y≥280 对话框区。
- 失败即报告，不得静默通过（见 `AGENTS.md` 的「消灭静默失败」）。

## 相关文档

- 画风规范：`docs/11_画风规范_90年代赛璐璐.md`
- 人物做法：`docs/03_人物的做法.md`
- 材质系统：`docs/09_材质系统.md`
- C6 颜色映射（参考 `naiz` 的 `tools/naiz_conv/mag_convert.py`）：`tools/pipeline_c/convert.py` 把前景裁切缩放后，按 spec 色板做 CIELAB 最近色映射，背景置 index 0 透明；不做材质语义分类，因此白衬衫与浅肤色不会互相误判。旧材质分类渲染仍留在 `tools/tachie/asset3.py`、`tools/tachie/matregion.py`，供管线 2 使用。
