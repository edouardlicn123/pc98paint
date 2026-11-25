# -*- coding: utf-8 -*-
"""Prompt assembly from docs/11 §3 (90s bishoujo game CG style guide)."""
from __future__ import annotations

import sys
from pathlib import Path

_COMMON = Path(__file__).resolve().parents[2] / "tools" / "common"
if str(_COMMON) not in sys.path:
    sys.path.insert(0, str(_COMMON))

import style as art_style  # noqa: E402

STYLE = art_style.with_credit(
    "1990s Japanese bishoujo game CG "
    "illustration in the Kanon-era galge "
    "style, very thin soft dark-brown line art with delicate inner hair-strand "
    "and cloth-fold lines that fade out on the lit side, soft airbrushed "
    "shading blended over 3-4 tones with edges smoothed across several pixels "
    "instead of hard bands, shadow hues shifted cooler and more saturated "
    "instead of just darker, single light source from the upper left, cast "
    "shadows drawn as smooth shapes (jaw shadow on the neck, crescent under "
    "the bust, soft band on the waist side, soft bands at cuffs and skirt "
    "pleats, cylindrical gradient down the right side of each leg), hair "
    "painted in 4-5 tones with long soft highlight streaks that follow "
    "individual strands and a few flyaway hairs, large glossy eyes with a "
    "layered iris gradient and several white specular highlights, smooth warm "
    "skin with airbrushed blush, saturated warm palette, clean silhouette"
)

NEGATIVE = (
    "photorealistic, 3d render, hard-edged posterized cel shading, flat "
    "two-tone vector fills, thick black outlines, sketch lines, extra fingers, "
    "deformed hands, cropped feet, text, watermark, signature, border, frame, "
    "harsh white scar across the hair, knit sweater texture on a sailor "
    "blouse, modern glossy anime rendering, nostril dots, two-dot nose, "
    "dot-only nose"
)

COMPOSITIONS = {
    "sheet": (
        "character reference sheet, three full-body views side by side "
        "(front, side, back), identical height and scale, neutral standing "
        "pose, arms relaxed, no perspective, flat pure white background, same "
        "line weight in all three views, no expression variation"
    ),
    "tachie": (
        "single full-body standing character art, facing the viewer straight "
        "on, head and torso square to the camera with no three-quarter turn, "
        "feet visible, hands relaxed at the sides, flat pure white background, "
        "no frame crop"
    ),
    "half": (
        "single half-body standing character art cropped just below the "
        "knees, facing the viewer straight on, head and torso square to the "
        "camera with no three-quarter turn, arms relaxed at the sides, flat "
        "pure white background, no frame crop, no feet"
    ),
    "closeup": (
        "bust portrait, head and shoulders, face occupying 35-45% of the "
        "frame, detailed eyes and hair strands, soft out-of-focus street "
        "background with low contrast, no crop on the top of the hair"
    ),
    "full": (
        "full body character art including shoes, standing straight facing the "
        "viewer, accurate body proportions, flat pure white background, "
        "complete silhouette"
    ),
}

PURPOSE = {
    "sheet": "character reference sheet",
    "tachie": "visual novel character tachie (standing sprite)",
    "half": "visual novel half-body tachie (knee-up standing sprite)",
    "closeup": "close-up bust portrait",
    "full": "full-body character art",
}


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value if item]


def _color_name(value):
    """Turn a hex ref into a plain English colour word for the prompt."""
    if not isinstance(value, str) or not value.startswith("#") or len(value) != 7:
        return str(value or "")
    import colorsys

    try:
        rgb = tuple(int(value[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
    except ValueError:
        return value
    h, s, v = colorsys.rgb_to_hsv(*rgb)
    deg = h * 360.0
    if v < 0.20:
        return "black"
    if s < 0.10:
        return "white" if v > 0.88 else "grey"
    if v > 0.82 and s < 0.30:
        return "cream" if 20 <= deg <= 60 else "pale grey"
    if v < 0.55 and 10 <= deg <= 55:
        return "brown"
    if deg < 15 or deg >= 345:
        return "pink" if v > 0.60 and s < 0.55 else "red"
    if 330 <= deg < 345:
        return "pink"
    if deg < 20:
        return "red"
    if deg < 45:
        return "orange"
    if deg < 70:
        return "yellow"
    if deg < 165:
        return "green"
    if deg < 200:
        return "teal"
    if deg < 250:
        return "blue"
    if deg < 300:
        return "purple"
    if 300 <= deg < 345:
        return "pink" if v > 0.60 else "magenta"
    return "pink"


def _ref(spec, material_id, index=0):
    """Return one hex ref of a material, tolerating missing materials."""
    aliases = {"blouse": ("top",), "skirt": ("bottom",),
               "collar": ("inner",), "bow": ("accent",),
               "top": ("blouse",), "bottom": ("skirt",),
               "inner": ("collar",), "accent": ("bow",)}
    by_id = {m.get("id"): m for m in spec.get("materials") or []}
    material = by_id.get(material_id)
    if material is None:
        for candidate in aliases.get(material_id, ()):
            if candidate in by_id:
                material = by_id[candidate]
                break
    if not material:
        return None
    refs = material.get("refs") or []
    if not refs:
        return None
    return refs[min(index, len(refs) - 1)]


def describe(spec):
    """Describe character, hair and outfit in one English clause.

    Colours are taken from the resolved material refs whenever available, so
    the prompt matches the palette that will actually be used by the PC-98
    conversion.  Every field stays optional (no ``KeyError`` on partial specs).
    """
    spec = spec or {}
    gender = spec.get("gender") or "character"
    hair = spec.get("hair") or {}
    face = spec.get("face") or {}
    outfit = spec.get("outfit") or {}

    hair_bits = []
    hair_color = (_color_name(_ref(spec, "hair", 1))
                  or _color_name(hair.get("color")) or "")
    length = str(hair.get("length") or "").replace("-", " ")
    style = str(hair.get("style") or "")
    length_word = {"waist": "long", "shoulder": "medium",
                   "short": "short", "long": "long"}.get(length, length)
    built = " ".join(part for part in (length_word, style, hair_color) if part)
    if built:
        hair_bits.append(f"{built} hair")
    if hair.get("bangs"):
        hair_bits.append(f"{hair['bangs']} bangs")
    hair_bits.append(
        "long soft highlight streaks following individual strands "
        "and a few flyaway hairs")

    face_bits = []
    iris = _color_name(_ref(spec, "iris", 0)) or _color_name(face.get("iris"))
    if iris:
        face_bits.append(f"{iris} eyes")
    for key in ("eye_size", "brows", "nose", "mouth"):
        if face.get(key):
            face_bits.append(str(face[key]))

    outfit_bits = []
    outfit_type = str(outfit.get("type") or "").lower()
    if "swim" in outfit_type:
        top = _color_name(_ref(spec, "top", 0))
        bottom = (_color_name(_ref(spec, "bottom", 1))
                  or _color_name(_ref(spec, "bottom", 0)))
        if top:
            outfit_bits.append(f"{top} bikini top")
        if bottom:
            outfit_bits.append(f"{bottom} bikini bottom")
    else:
        is_sailor = outfit_type.startswith("sailor")
        top = _color_name(_ref(spec, "blouse", 0))
        collar = _color_name(_ref(spec, "collar", 1)) or _color_name(
            _ref(spec, "collar", 0))
        bow = _color_name(_ref(spec, "bow", 0))
        skirt = _color_name(_ref(spec, "skirt", 1))
        shoes = _color_name(_ref(spec, "shoes", 0)) or "black"
        if top:
            outfit_bits.append(
                f"{top} " + ("sailor blouse" if is_sailor else "top"))
        if collar:
            outfit_bits.append(f"{collar} sailor collar")
        if bow:
            outfit_bits.append(f"{bow} ribbon bow")
        if skirt:
            outfit_bits.append(f"{skirt} pleated skirt")
        outfit_bits.append(f"{shoes} loafers")
        if not top and not skirt:
            outfit_bits = []
            for key in ("base", "collar", "accent", "bottom", "neckwear", "shoes"):
                if outfit.get(key):
                    outfit_bits.append(str(outfit[key]))
            if not outfit_bits and outfit.get("type"):
                outfit_bits.append(str(outfit["type"]))

    segments = []
    if hair_bits:
        segments.append(", ".join(hair_bits))
    if face_bits:
        segments.append(", ".join(face_bits))
    if outfit_bits:
        segments.append("wearing " + ", ".join(outfit_bits))
    if not segments:
        return f"a {gender} character"
    return f"a {gender} character, " + ", ".join(segments)


def build(spec, kind):
    """Assemble purpose + character + style + composition + negative blocks."""
    if kind not in COMPOSITIONS:
        raise ValueError(
            f"unknown kind {kind!r}; expected one of {sorted(COMPOSITIONS)}")
    overrides = _as_list((spec or {}).get("overrides"))
    details = ""
    if overrides:
        details = " Character details: " + "; ".join(overrides) + "."
    blocks = [
        f"{PURPOSE[kind]}, {describe(spec)}." + details,
        STYLE + ".",
        COMPOSITIONS[kind] + ".",
        "Negative prompt: " + NEGATIVE + ".",
    ]
    outfit_type = str(
        ((spec or {}).get("outfit") or {}).get("type") or "").lower()
    if "swim" in outfit_type:
        blocks.insert(2, art_style.swimwear_clause() + ".")
    return " ".join(blocks)
