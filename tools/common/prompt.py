# -*- coding: utf-8 -*-
"""由 Spec（可为模板合并后的实例）构造生成提示词与负面词。

机位、档位、表情是硬约束：
- 默认 half + neutral + eye-level；
- 禁止俯视/仰视，禁止把半身画成全身再裁；
- 眼睛必须两只都有纯白高光，否则 lint 不通过。

体型 token 来自 effective ``body`` / ``proportions``，不再在 STYLE_POS 里硬编码
头身数与肩宽，避免模板切换后提示词仍写死「6 头身、窄肩」。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import schema
import style as art_style
import template

STYLE_POS = art_style.with_credit(
    "1990s PC-98 visual novel character CG, cel-shaded, hard-edged flat shading, "
    "3-4 tones per material, ring-iris large eyes, blocky hair masses, simplified nose and mouth, "
    "1px dark line art, cool hue-shifted shadows, "
    "warm cream cloth highlights, pure white eye highlights, "
    "low local contrast, solid white background, no gradients"
)
STYLE_NEG = (
    "modern anime, 8-head proportions, detailed hair strands, soft shading, gradient shading, "
    "oily skin, wet skin, sweaty skin, volumetric light, blurry, painterly, text, watermark"
)

TIER_TEXT = {
    "closeup": "close-up bust portrait (head and shoulders only)",
    "half": "half-body character sprite from head to mid-thigh",
    "full": "full body front view character sprite",
}
CAMERA_TEXT = "eye-level camera, straight-on view, no high angle, no low angle"
EXPR_TEXT = {
    "neutral": "calm neutral expression, closed mouth",
    "smile": "gentle closed-mouth smile",
    "sad": "sad expression, slightly downturned mouth",
    "surprised": "surprised expression, slightly open mouth",
    "shy": "shy expression, blushing cheeks",
}


def body_tokens(spec):
    """从合并后的 body/proportions 生成头身、肩宽、脸宽 token。"""
    body = spec.get("body") or {}
    proportions = spec.get("proportions") or {}
    heads = proportions.get("heads", body.get("heads"))
    tokens = []
    if heads:
        tokens.append(f"{heads} head proportions")
    shoulder = body.get("shoulder_ratio")
    if shoulder:
        band = ("narrow" if shoulder < 1.5
                else "adult" if shoulder < 2.2 else "broad")
        tokens.append(
            f"shoulder width {shoulder:.2f} head heights ({band} shoulders)")
    face_width = body.get("face_width_ratio")
    if face_width:
        tokens.append(f"face width {face_width:.2f} head heights")
    bust = body.get("bust") or {}
    if bust.get("size", 0) >= 2:
        tokens.append("visible bust volume")
    return ", ".join(tokens)


def hair_tokens(spec):
    hair = spec.get("hair") or {}
    length = hair.get("length", "medium")
    color = hair.get("color") or hair.get("color_family", "natural")
    parts = [f"{length} {color} hair"]
    if hair.get("bangs"):
        parts.append(f"{hair['bangs']} bangs")
    if hair.get("tie") and hair["tie"] != "none":
        parts.append(f"{hair['tie']} tie")
    if hair.get("style"):
        parts.append(hair["style"])
    reflection = hair.get("highlight") or hair.get("reflection")
    if reflection:
        parts.append(f"{reflection} block highlights")
    return ", ".join(parts)


def face_tokens(spec):
    face = spec.get("face") or {}
    parts = []
    for key in ("shape", "eyes", "eye_size", "brows", "nose", "mouth"):
        if face.get(key):
            parts.append(str(face[key]))
    markings = face.get("markings") or []
    if isinstance(markings, str):
        markings = [markings]
    parts.extend(str(item) for item in markings if item)
    return ", ".join(parts)


def outfit_tokens(spec):
    outfit = spec.get("outfit") or {}
    parts = []
    for key in ("type", "base", "collar", "accent", "bottom", "neckwear"):
        if outfit.get(key):
            parts.append(str(outfit[key]))
    return ", ".join(parts)


def build(spec):
    r = spec.get("render", {})
    tier = r.get("tier", "half")
    expr = r.get("expression", "neutral")
    if tier not in TIER_TEXT:
        raise ValueError(f"未知档位: {tier}")
    if expr not in EXPR_TEXT:
        raise ValueError(f"未知表情: {expr}")
    tokens = [TIER_TEXT[tier], f"a {spec['gender']} character"]
    for block in (body_tokens(spec), hair_tokens(spec), face_tokens(spec),
                  outfit_tokens(spec)):
        if block:
            tokens.append(block)
    tokens.extend([
        CAMERA_TEXT,
        EXPR_TEXT[expr],
        "both eyes open, one small pure-white highlight on the upper-left of each iris",
        "identical size and position on both eyes",
        STYLE_POS,
    ])
    return ", ".join(tokens), STYLE_NEG


def main():
    parser = argparse.ArgumentParser(description="预览角色生成提示词")
    parser.add_argument("--spec", required=True, help="角色 spec.json 路径")
    args = parser.parse_args()
    spec = schema.load(Path(args.spec))
    effective, meta = template.resolve_template(spec)
    positive, negative = build(effective)
    print(f"TEMPLATE: {meta['resolved_template']}")
    print(f"POSITIVE: {positive}")
    print(f"NEGATIVE: {negative}")


if __name__ == "__main__":
    main()
