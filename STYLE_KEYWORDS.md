# 全局强制画风关键字

> **单一事实源**。每次生成图像前必须读本文件；所有 prompt 必须以 `CREDIT` 行开头。
> 与 `tools/common/style.py` 联动：该模块导入时读取本文件的 `CREDIT` / `REQUIRED` 行，缺失即 `RuntimeError`。

CREDIT: in the style of artist 高橋ショウ (Takahashi Shou) of studio 海月製作所 (Kaigetsu Seisakusho), and artists 十重五重 (Toegoe) and 松俊

REQUIRED: 高橋ショウ
REQUIRED: 海月製作所
REQUIRED: 十重五重
REQUIRED: 松俊

## 条件强制：泳装

> 画面中的角色穿泳装（`swimwear` / bikini / one-piece 等）时，以下两条必须写入 prompt。
> `tools/pipeline_c/prompt.py` 检测到 `spec.outfit.type` 含 `swim` 时自动追加。

SWIM_REQUIRED: Swimsuit fabric stays smooth and opaque; at the lower edge show only tension lines and shading, with no anatomical detail or body contour through the cloth.
SWIM_REQUIRED: Show the top's fit only with short folds under the bust and slight strap pressure marks; keep the fabric surface smooth and undetailed.

## 身材比例（强制）

> 三视图与立绘一律按正常人体比例绘制，禁止 Q 版 / SD 化；`with_credit()` 统一下发。

BODY_REQUIRED: 1990s galge proportions, about 7.5 head heights tall, oval face about 1.3 times taller than wide, eye line at half the head height, slender neck, natural shoulder width, straight waist with a natural and not exaggerated hip line, long legs, hands and feet in realistic size.
BODY_REQUIRED: Mature facial structure with a defined chin, jawline and nose bridge, normal forehead height; not chibi, not super-deformed, no oversized head, no wide round face, no baby-face proportions, no short limbs, no tiny hands, no SD mascot look.

## 五官画法（强制，2026-11-25）

> 三视图生成时的五官规则；生成后由 `tools/pipeline_c/convert._redraw_nose` / `_redraw_mouth`
> 在正面视图上确定性重画（见 AGENTS「鼻子与嘴巴强制修正落在三视图上」）。
> `with_credit()` 统一下发，缺 `FACE_REQUIRED` 行即 `RuntimeError`。

FACE_REQUIRED: Nose is a small solid filled diamond with no outline, filled with a skin shadow tone two steps darker than the skin; it never has a rim line, nostril dots or a bridge line.
FACE_REQUIRED: Mouth is one single thin smile arc; both ends sit on the same height and the middle dips gently downward, drawn with a soft brown line about 30% lighter than the outline; no double dash, no tiny two-dot mouth, no lip fill, no teeth.

