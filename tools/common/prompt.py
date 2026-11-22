# -*- coding: utf-8 -*-
"""由 Spec 构造生成提示词与负面词。

机位、档位、表情是硬约束：
- 默认 half + neutral + eye-level；
- 禁止俯视/仰视，禁止把半身画成全身再裁；
- 眼睛必须两只都有纯白高光，否则 lint 不通过。
"""

STYLE_POS = (
    "1990s PC-98 visual novel character CG, cel-shaded, hard-edged flat shading, "
    "3-4 tones per material, ring-iris large eyes, blocky hair masses, simplified nose and mouth, "
    "6-head proportions, narrow shoulders, 1px dark line art, cool hue-shifted shadows, "
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


def build(spec):
    p = spec["proportions"]
    h = spec["hair"]
    o = spec["outfit"]
    r = spec.get("render", {})
    tier = r.get("tier", "half")
    expr = r.get("expression", "neutral")
    if tier not in TIER_TEXT:
        raise ValueError(f"未知档位: {tier}")
    if expr not in EXPR_TEXT:
        raise ValueError(f"未知表情: {expr}")
    pos = (
        f"{TIER_TEXT[tier]} of a {spec['gender']} character, {p['heads']} head proportions, "
        f"{CAMERA_TEXT}, "
        f"{h['length']} {h['color']} hair with {h['bangs_blocks']} bang blocks and {h['highlight']} block highlights, "
        f"{o['type']} uniform, {o['base']} base, {o['collar']} collar, {o['accent']} accent, "
        f"{EXPR_TEXT[expr]}, "
        "both eyes open, one small pure-white highlight on the upper-left of each iris, "
        "identical size and position on both eyes, "
        + STYLE_POS
    )
    return pos, STYLE_NEG
