# -*- coding: utf-8 -*-
"""三层人物模板：原型（archetype）→ 着装变体（outfit）→ 角色实例（spec）。

数据目录固定为 ``characters/templates/``：

- ``archetypes/<id>.json``：体型、脸型、发型（跨着装共享）
- ``outfits/<id>.json``：服装结构、材质、绘制配置（校服/常服分离）
- ``index.json``：注册表与自动匹配关键词

``resolve_template`` 只做静态 JSON 合并，不在运行时读参考图或做最近邻检索。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "characters" / "templates"

_MERGE_FROM_TEMPLATE = ("face", "hair", "outfit", "materials", "drawing",
                        "garment_layers")


def _read_json(path):
    path = Path(path)
    if not path.exists():
        raise ValueError(f"模板文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_index(templates_dir=None):
    root = Path(templates_dir) if templates_dir else TEMPLATE_DIR
    index = _read_json(root / "index.json")
    if not isinstance(index, dict):
        raise ValueError("index.json 必须是对象")
    for key in ("archetypes", "outfits"):
        if not isinstance(index.get(key), list):
            raise ValueError(f"index.json 缺少 {key} 列表")
    return index


def load_archetype(archetype_id, templates_dir=None):
    root = Path(templates_dir) if templates_dir else TEMPLATE_DIR
    return _read_json(root / "archetypes" / f"{archetype_id}.json")


def load_outfit(outfit_id, templates_dir=None):
    root = Path(templates_dir) if templates_dir else TEMPLATE_DIR
    return _read_json(root / "outfits" / f"{outfit_id}.json")


def _index_maps(index):
    archetypes = {item["id"]: item for item in index["archetypes"]}
    outfits = {item["id"]: item for item in index["outfits"]}
    return archetypes, outfits


def infer_age_group(proportions):
    """按头身比推断年龄组；仅用于自动匹配打分，不写回实例。"""
    heads = float((proportions or {}).get("heads", 0) or 0)
    if 0 < heads <= 5.9:
        return "child"
    if heads <= 6.9:
        return "teen"
    if heads > 0:
        return "adult"
    return None


def _score(entry, spec, outfit_type, age_group, outfits_index=None):
    score = 0
    gender = spec.get("gender")
    if gender and entry.get("gender") == gender:
        score += 4
    elif entry.get("gender") and gender:
        score -= 100
    types = {(outfits_index or {}).get(oid, {}).get("type")
             for oid in entry.get("outfits", [])}
    if outfit_type and (entry.get("outfit_type") == outfit_type
                        or outfit_type in types):
        score += 3
    if age_group and entry.get("age_group") == age_group:
        score += 2
    name = f"{spec.get('name', '')} {spec.get('id', '')}"
    for keyword in entry.get("keywords", []):
        if keyword and keyword in name:
            score += 1
    return score


def _pick_outfit(entry, outfit_type, outfits_index):
    candidates = list(entry.get("outfits", []))
    if not candidates:
        raise ValueError(f"原型 {entry['id']} 未挂载任何 outfit")
    if outfit_type:
        typed = [oid for oid in candidates
                 if outfits_index.get(oid, {}).get("type") == outfit_type]
        if typed:
            candidates = typed
    return sorted(candidates)[0]


def auto_select(spec, templates_dir=None):
    """按 gender + outfit.type + 年龄/关键词确定性选择原型与变体。"""
    index = load_index(templates_dir)
    archetypes, outfits = _index_maps(index)
    outfit_type = (spec.get("outfit") or {}).get("type")
    age_group = spec.get("age_group") or infer_age_group(spec.get("proportions"))
    ranked = sorted(
        index["archetypes"],
        key=lambda item: (-_score(item, spec, outfit_type, age_group, outfits),
                          str(item.get("ref", "")), item["id"]),
    )
    if not ranked:
        raise ValueError("index.json 中没有可用原型")
    best = ranked[0]
    outfit_id = _pick_outfit(best, outfit_type, outfits)
    score = _score(best, spec, outfit_type, age_group, outfits)
    return best["id"], outfit_id, score


def resolve_template(spec, templates_dir=None):
    """返回 ``(effective, meta)``；face/hair 保留实例，渲染配置以模板为准。"""
    template = spec.get("template")
    if template:
        if not isinstance(template, dict) or not template.get("archetype"):
            raise ValueError("template 必须是含 archetype 的对象")
        archetype_id = template["archetype"]
        index = load_index(templates_dir)
        _, outfits = _index_maps(index)
        archetype = load_archetype(archetype_id, templates_dir)
        outfit_id = template.get("outfit")
        if outfit_id:
            outfit = load_outfit(outfit_id, templates_dir)
            if outfit.get("archetype") != archetype_id:
                raise ValueError(
                    f"outfit {outfit_id} 不属于原型 {archetype_id}")
        else:
            outfit_id = _pick_outfit(
                {"id": archetype_id,
                 "outfits": next((item.get("outfits", [])
                                  for item in index["archetypes"]
                                  if item["id"] == archetype_id), [])},
                (spec.get("outfit") or {}).get("type"), outfits)
            outfit = load_outfit(outfit_id, templates_dir)
        source, score = "explicit", None
    else:
        archetype_id, outfit_id, score = auto_select(spec, templates_dir)
        archetype = load_archetype(archetype_id, templates_dir)
        outfit = load_outfit(outfit_id, templates_dir)
        source = "auto"

    effective = copy.deepcopy(spec)
    if "body" in archetype:
        effective["body"] = deep_merge(
            copy.deepcopy(archetype["body"]), spec.get("body") or {})
    for key in ("face", "hair"):
        if key not in spec and key in archetype:
            effective[key] = copy.deepcopy(archetype[key])
    for key in _MERGE_FROM_TEMPLATE:
        if key in ("face", "hair"):
            continue
        if key in outfit:
            effective[key] = copy.deepcopy(outfit[key])

    meta = {
        "resolved_template": {
            "archetype": archetype_id,
            "outfit": outfit_id,
            "source": source,
            "score": score,
            "applied_body": "body" in effective,
        }
    }
    return effective, meta


def deep_merge(base, override):
    """递归合并字典；列表整体替换（materials/folds 不拼接）。"""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out
