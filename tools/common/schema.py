# -*- coding: utf-8 -*-
"""角色规格：加载、校验、提供默认值。"""
import json
from pathlib import Path

REQUIRED = ("id", "gender", "proportions", "hair", "outfit", "palette", "render")


def validate_drawing(config, materials):
    """校验绘制锚点、材质表面与 refs 色调索引；非法配置直接拒绝。"""
    if config is None:
        return
    by_id = {m["id"]: m for m in materials}
    if config.get("light", "upper-left") != "upper-left":
        raise ValueError("drawing.light 当前只支持 upper-left")

    def point(value, label):
        if (not isinstance(value, (list, tuple)) or len(value) != 2
                or not all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in value)):
            raise ValueError(f"{label} 必须是 0–1 归一化二维坐标")

    def path(cfg, label):
        values = cfg.get("path")
        if values is None:
            if "from" not in cfg or "to" not in cfg:
                raise ValueError(f"{label} 需要 path 或 from/to")
            values = [cfg["from"], cfg["to"]]
        if len(values) < 2:
            raise ValueError(f"{label}.path 至少需要两点")
        for value in values:
            point(value, label)
        if not isinstance(cfg.get("width", 2), (int, float)) or cfg.get("width", 2) <= 0:
            raise ValueError(f"{label}.width 必须大于 0")

    def tone(material, value, label):
        if value is None:
            return
        if (not isinstance(value, int) or isinstance(value, bool)
                or not 0 <= value < len(material.get("refs", []))):
            raise ValueError(f"{label}.tone 必须引用所属材质的既有 refs 索引")

    for material_id, surface in config.get("materials", {}).items():
        if material_id not in by_id:
            raise ValueError(f"drawing.materials 含未知材质: {material_id}")
        kind = surface.get("surface", "plain")
        if kind not in ("plain", "plaid", "fur", "swimwear"):
            raise ValueError(f"未知 surface: {kind}")
        material = by_id[material_id]
        if kind == "plaid":
            spacing = surface.get("spacing", 6)
            values = spacing if isinstance(spacing, list) else [spacing]
            if not values or not all(isinstance(v, int) and v > 0 for v in values):
                raise ValueError("plaid.spacing 必须是正整数或正整数列表")
            for key in ("axis", "cross_axis"):
                if key in surface:
                    axis = surface[key]
                    if (not isinstance(axis, list) or len(axis) != 2
                            or not all(isinstance(v, (int, float)) for v in axis)
                            or not any(axis)):
                        raise ValueError(f"plaid.{key} 必须是非零二维向量")
            for value in surface.get("tones", []):
                tone(material, value, f"plaid.{material_id}")
        elif kind == "fur":
            tone(material, surface.get("tone"), f"fur.{material_id}")
        elif kind == "swimwear":
            for arc in surface.get("arcs", []):
                path(arc, f"swimwear.{material_id}.arc")
                tone(material, arc.get("tone"), f"swimwear.{material_id}.arc")

    for cfg in config.get("folds", []):
        material = by_id.get(cfg.get("material"))
        if material is None or material.get("role") not in ("white", "cloth"):
            raise ValueError(f"fold 材质必须是已有 white/cloth: {cfg.get('material')}")
        if cfg.get("kind", "pinch") not in ("radiate", "pinch", "seam"):
            raise ValueError(f"未知 fold kind: {cfg.get('kind')}")
        path(cfg, f"fold.{material['id']}")
        tone(material, cfg.get("tone"), f"fold.{material['id']}")

    for cfg in config.get("occlusions", []):
        if cfg.get("over") not in by_id or cfg.get("under") not in by_id:
            raise ValueError("occlusion.over/under 必须引用已有材质")
        if cfg["over"] == cfg["under"]:
            raise ValueError("occlusion.over/under 不能相同")
        if cfg.get("path"):
            path(cfg, "occlusion")
        elif cfg.get("width", 2) <= 0:
            raise ValueError("occlusion.width 必须大于 0")
        tone(by_id[cfg["under"]], cfg.get("tone"), "occlusion")

    for cfg in config.get("highlights", []):
        material = by_id.get(cfg.get("material"))
        if material is None or material.get("role") not in ("white", "cloth"):
            raise ValueError(f"highlight 材质必须是已有 white/cloth: {cfg.get('material')}")
        path(cfg, f"highlight.{material['id']}")
        tone(material, cfg.get("tone"), f"highlight.{material['id']}")


def load(path):
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in REQUIRED:
        if key not in spec:
            raise ValueError(f"spec 缺少字段: {key}")

    p = spec["proportions"]
    if not 5.0 <= p.get("heads", 0) <= 7.5:
        raise ValueError("heads 应在 5.0–7.5 之间")
    lo, hi = p.get("eye_width_ratio", [0, 1])
    if not (0 < lo <= hi < 1):
        raise ValueError("eye_width_ratio 非法")

    r = spec["render"]
    r.setdefault("sprite_h", 640)
    r.setdefault("sprite_w_max", 300)
    r.setdefault("line_darken", 0.55)
    r.setdefault("dither_density", 0.5)
    r.setdefault("dither_band", 2)
    r.setdefault("palette_max", 256)
    r.setdefault("tier", "half")
    r.setdefault("expression", "neutral")
    r.setdefault("camera", "eye-level")
    if r["tier"] not in ("closeup", "half", "full"):
        raise ValueError(f"render.tier 非法: {r['tier']}")
    if r["expression"] not in ("neutral", "smile", "sad", "surprised", "shy"):
        raise ValueError(f"render.expression 非法: {r['expression']}")
    if r["camera"] != "eye-level":
        raise ValueError("立绘只允许平视（camera 必须是 eye-level）")

    spec.setdefault("checks", {
        "neutral_gray_max": 0.06,
        "outline_min": 0.65,
        "dark_chroma_min": 12,
        "hair_tones": [3, 8],
    })
    validate_drawing(spec.get("drawing"), spec.get("materials", []))
    return spec
