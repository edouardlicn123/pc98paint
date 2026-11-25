# -*- coding: utf-8 -*-
"""Structured brief -> character spec skeleton -> resolved effective spec.

The brief is the only input of pipeline C.  It is intentionally small:
gender / age_group / outfit_type / name drive ``template.auto_select`` while
optional ``proportions`` / ``hair`` / ``face`` / ``outfit`` override the
template values, and ``colors`` re-tints the outfit materials so that a new
character does not inherit the template character's palette.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_COMMON = ROOT / "tools" / "common"
if str(_COMMON) not in sys.path:
    sys.path.insert(0, str(_COMMON))

import template  # noqa: E402

# Fallback head proportions per age group.  Only used when the brief does not
# provide ``proportions``; the template body itself stays untouched.
_AGE_HEADS = {"child": 5.5, "teen": 6.2, "adult": 6.8}
DEFAULT_EYE_WIDTH = [0.4, 0.5]


def _deep(value):
    return copy.deepcopy(value) if value is not None else None


def build_spec(brief, slug):
    """Turn a structured brief into a character spec skeleton.

    ``hair`` / ``face`` / ``outfit`` are only emitted when the brief provides
    them, so that ``template.resolve_template`` can fill missing blocks from
    the archetype / outfit templates instead of merging into an empty dict.
    """
    if not isinstance(brief, dict):
        raise ValueError("brief must be an object")
    age_group = brief.get("age_group") or "teen"
    proportions = {"heads": _AGE_HEADS.get(age_group, 6.2),
                   "eye_width_ratio": list(DEFAULT_EYE_WIDTH)}
    proportions.update(_deep(brief.get("proportions")) or {})

    spec = {
        "id": slug,
        "name": brief.get("name") or slug,
        "gender": brief.get("gender") or "female",
        "age_group": age_group,
        "proportions": proportions,
        "palette": _deep(brief.get("palette")) or {},
        "render": _deep(brief.get("render")) or {},
    }
    outfit = _deep(brief.get("outfit")) or {}
    if brief.get("outfit_type"):
        outfit.setdefault("type", brief["outfit_type"])
    if outfit:
        spec["outfit"] = outfit
    for key in ("hair", "face"):
        value = _deep(brief.get(key))
        if value:
            spec[key] = value
    if brief.get("overrides"):
        spec["overrides"] = _deep(brief["overrides"])
    # An explicit template pins the archetype/outfit instead of auto-selecting.
    # It matters when only one outfit carries the material ids the brief tints
    # (e.g. momo_sailor has blouse/collar/skirt/bow, most others do not).
    pinned = _deep(brief.get("template"))
    if pinned:
        if not pinned.get("archetype"):
            raise ValueError("brief.template must contain an archetype")
        spec["template"] = pinned
    return spec


def _hex_to_rgb(value):
    if not isinstance(value, str) or not value.startswith("#") or len(value) != 7:
        raise ValueError(f"color must be #rrggbb, got {value!r}")
    try:
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
    except ValueError as exc:
        raise ValueError(f"color must be #rrggbb, got {value!r}") from exc


def _rgb_to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _clamp(value, lo=0.0, hi=1.0):
    return max(lo, min(hi, value))


def _derive_tones(color):
    """Derive light / mid / dark tones from a single color.

    Follows docs/11 §4: mid keeps the source color, light is brighter with
    lower saturation, dark is darker with higher saturation and a cooler hue.
    """
    import colorsys

    r, g, b = (channel / 255.0 for channel in _hex_to_rgb(color))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    light = colorsys.hls_to_rgb(h, _clamp(l + (1.0 - l) * 0.45),
                                _clamp(s * 0.72))
    dark = colorsys.hls_to_rgb((h - 18.0 / 360.0) % 1.0, _clamp(l * 0.55),
                               _clamp(s * 1.18))
    to_hex = lambda c: _rgb_to_hex(  # noqa: E731
        tuple(int(round(channel * 255.0)) for channel in c))
    return [to_hex(light), color, to_hex(dark)]


def _normalize_refs(name, colors):
    if isinstance(colors, str):
        colors = [colors]
    if not isinstance(colors, list) or not colors:
        raise ValueError(f"colors.{name} must be a non-empty list")
    for item in colors:
        _hex_to_rgb(item)
    if len(colors) == 1:
        return _derive_tones(colors[0]), True
    return list(colors), False


def _apply_colors(effective, colors):
    """Override material refs by id; role / paint always stay untouched."""
    report = {"applied": [], "derived": [], "ignored": []}
    if not colors:
        return report
    if not isinstance(colors, dict):
        raise ValueError("brief.colors must be an object")
    materials = effective.get("materials") or []
    by_id = {material.get("id"): material for material in materials}
    for material_id, values in colors.items():
        target = _resolve_material_id(material_id, by_id)
        material = by_id.get(target)
        if material is None:
            report["ignored"].append(material_id)
            continue
        refs, derived = _normalize_refs(target, values)
        material["refs"] = refs
        report["applied"].append(target)
        if derived:
            report["derived"].append(target)
    return report


# Outfits name the same garment differently (momo_sailor: blouse/skirt/bow,
# most others: top/bottom/accent).  A brief uses one vocabulary, so fall back
# to the sibling id before giving up.
_ID_ALIASES = {
    "blouse": ("top",), "skirt": ("bottom",), "collar": ("inner",),
    "bow": ("accent",), "top": ("blouse",), "bottom": ("skirt",),
    "inner": ("collar",), "accent": ("bow",),
}


def _resolve_material_id(material_id, by_id):
    if material_id in by_id:
        return material_id
    for candidate in _ID_ALIASES.get(material_id, ()):
        if candidate in by_id:
            return candidate
    return material_id


def _matched_keywords(index, archetype_id, spec):
    entry = next((item for item in index["archetypes"]
                  if item.get("id") == archetype_id), None)
    if entry is None:
        return []
    haystack = f"{spec.get('name', '')} {spec.get('id', '')}"
    return [keyword for keyword in entry.get("keywords", [])
            if keyword and keyword in haystack]


def resolve(brief, templates_dir=None):
    """Select a template and return the merged ``(effective, meta)`` spec."""
    slug = brief.get("slug") or brief.get("id") or "character"
    spec = build_spec(brief, slug)
    index = template.load_index(templates_dir)
    if spec.get("template"):
        effective, meta = template.resolve_template(spec, templates_dir)
        meta["auto_select"] = None
        archetype_id = meta["resolved_template"]["archetype"]
    else:
        archetype_id, outfit_id, score = template.auto_select(spec, templates_dir)
        merged = {"template": {"archetype": archetype_id, "outfit": outfit_id},
                  **spec}
        effective, meta = template.resolve_template(merged, templates_dir)
        meta["auto_select"] = {"archetype": archetype_id, "outfit": outfit_id,
                               "score": score}
    meta["matched_keywords"] = _matched_keywords(index, archetype_id, spec)
    meta["colors"] = _apply_colors(effective, brief.get("colors"))
    return effective, meta


def resolve_spec(spec, templates_dir=None):
    """Resolve a stored character spec without losing its own material colours.

    ``template.resolve_template`` merges the outfit's materials over the spec,
    which would silently revert the refs written by ``brief``.  A spec that
    carries its own ``materials`` / ``palette`` always wins.
    """
    effective, meta = template.resolve_template(spec, templates_dir)
    for key in ("materials", "palette", "drawing", "body", "proportions",
                "overrides"):
        if spec.get(key):
            effective[key] = _deep(spec[key])
    return effective, meta


def write_spec(effective, path):
    """Write a spec with UTF-8 text preserved (``ensure_ascii=False``)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(effective, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    return target
