# -*- coding: utf-8 -*-
"""角色规格：加载、校验、提供默认值。"""
import json
import re
from pathlib import Path

REQUIRED = ("id", "gender", "proportions", "hair", "outfit", "palette", "render")
TEMPLATE_ROOT = Path(__file__).resolve().parents[2] / "characters" / "templates"
SLUG = re.compile(r"^[a-z][a-z0-9_]*$")


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _range(value, lo, hi, label):
    if not _is_number(value) or not lo <= value <= hi:
        raise ValueError(f"{label} 应在 {lo}–{hi} 之间")
    return float(value)


def validate_body(body):
    """校验体型字段；仅供模板与新增实例使用，旧 spec 可缺省。"""
    if body is None:
        return
    if not isinstance(body, dict):
        raise ValueError("body 必须是对象")
    _range(body.get("heads"), 5.0, 7.5, "body.heads")
    _range(body.get("shoulder_ratio"), 0.8, 2.5, "body.shoulder_ratio")
    _range(body.get("waist_ratio", 0.50), 0.3, 1.2, "body.waist_ratio")
    _range(body.get("face_width_ratio", 0.65), 0.4, 1.0,
           "body.face_width_ratio")
    if not isinstance(body.get("pose", "standing_front"), str):
        raise ValueError("body.pose 必须是字符串")
    bust = body.get("bust", {})
    if not isinstance(bust, dict):
        raise ValueError("body.bust 必须是对象")
    size = bust.get("size", 0)
    if (not isinstance(size, int) or isinstance(size, bool)
            or not 0 <= size <= 4):
        raise ValueError("body.bust.size 必须是 0–4 的整数")
    _range(bust.get("center_y_head", 2.45), 0, 6, "body.bust.center_y_head")
    _range(bust.get("separation", 0.55), 0, 1, "body.bust.separation")
    under = bust.get("under_boob_y_head")
    if under is not None:
        _range(under, 0, 6, "body.bust.under_boob_y_head")
    _range(bust.get("projection", 0.0), -1, 1, "body.bust.projection")
    torso = body.get("torso", {})
    if not isinstance(torso, dict):
        raise ValueError("body.torso 必须是对象")
    _range(torso.get("lean", 0.0), -0.5, 0.5, "body.torso.lean")


def validate_garment_layers(layers, materials):
    """层叠声明中的 id 必须与材质 id 一一对应，over 只能引用材质或保留字 skin。"""
    if layers is None:
        return
    if not isinstance(layers, list) or not layers:
        raise ValueError("garment_layers 必须是非空列表")
    material_ids = {m.get("id") for m in materials or []}
    layer_ids = set()
    for layer in layers:
        if not isinstance(layer, dict) or not layer.get("id"):
            raise ValueError("garment_layers 每一项必须有 id")
        layer_id = layer["id"]
        if layer_id not in material_ids:
            raise ValueError(f"garment_layers 含未知材质: {layer_id}")
        if layer_id in layer_ids:
            raise ValueError(f"garment_layers id 重复: {layer_id}")
        layer_ids.add(layer_id)
        over = layer.get("over", [])
        if not isinstance(over, list):
            raise ValueError(f"garment_layers.{layer_id}.over 必须是列表")
        for ref in over:
            if ref != "skin" and ref not in material_ids:
                raise ValueError(
                    f"garment_layers.{layer_id}.over 含未知层: {ref}")
        if not isinstance(layer.get("occludes_below", False), bool):
            raise ValueError(
                f"garment_layers.{layer_id}.occludes_below 必须是布尔值")


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
        derive = cfg.get("derive")
        if derive is not None:
            if derive != "layer_edge":
                raise ValueError("occlusion.derive 只支持 layer_edge")
            if cfg.get("path") or cfg.get("from") or cfg.get("to"):
                raise ValueError("occlusion 不能同时给 path 与 derive")
            if not _is_number(cfg.get("width", 2)) or cfg.get("width", 2) <= 0:
                raise ValueError("occlusion.width 必须大于 0")
        elif cfg.get("path"):
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


def validate_template_ref(ref, templates_dir=None):
    """校验 spec.template 的 archetype/outfit 引用实际存在。"""
    if ref is None:
        return
    if not isinstance(ref, dict) or not ref.get("archetype"):
        raise ValueError("template 必须是含 archetype 的对象")
    root = Path(templates_dir) if templates_dir else TEMPLATE_ROOT
    arch_id = ref["archetype"]
    if not SLUG.match(arch_id):
        raise ValueError(f"template.archetype 非法: {arch_id}")
    arch_path = root / "archetypes" / f"{arch_id}.json"
    if not arch_path.exists():
        raise ValueError(f"template.archetype 不存在: {arch_id}")
    outfit_id = ref.get("outfit")
    if outfit_id:
        if not SLUG.match(outfit_id):
            raise ValueError(f"template.outfit 非法: {outfit_id}")
        outfit_path = root / "outfits" / f"{outfit_id}.json"
        if not outfit_path.exists():
            raise ValueError(f"template.outfit 不存在: {outfit_id}")
        outfit = json.loads(outfit_path.read_text(encoding="utf-8"))
        if outfit.get("archetype") != arch_id:
            raise ValueError(
                f"template.outfit {outfit_id} 不属于 {arch_id}")


def validate_archetype(template):
    for key in ("id", "name", "ref", "gender", "body", "face", "hair"):
        if key not in template:
            raise ValueError(f"archetype 缺少字段: {key}")
    if not SLUG.match(str(template["id"])):
        raise ValueError(f"archetype.id 非法: {template['id']}")
    if template["gender"] not in ("male", "female"):
        raise ValueError("archetype.gender 必须是 male/female")
    if template.get("age_group") not in ("child", "teen", "adult"):
        raise ValueError("archetype.age_group 必须是 child/teen/adult")
    validate_body(template["body"])
    face = template["face"]
    for key in ("shape", "eyes", "eye_size", "brows", "nose", "mouth",
                "markings"):
        if key not in face:
            raise ValueError(f"archetype.face 缺少字段: {key}")
    hair = template["hair"]
    for key in ("length", "bangs", "tie", "style", "color_family",
                "reflection"):
        if key not in hair:
            raise ValueError(f"archetype.hair 缺少字段: {key}")
    return template


def validate_outfit(template):
    for key in ("id", "archetype", "type", "garment_layers", "materials",
                "drawing"):
        if key not in template:
            raise ValueError(f"outfit 缺少字段: {key}")
    if not SLUG.match(str(template["id"])):
        raise ValueError(f"outfit.id 非法: {template['id']}")
    if not SLUG.match(str(template["archetype"])):
        raise ValueError(f"outfit.archetype 非法: {template['archetype']}")
    materials = template["materials"]
    if not isinstance(materials, list) or not materials:
        raise ValueError("outfit.materials 必须是非空列表")
    ids = set()
    for material in materials:
        if not isinstance(material, dict) or not material.get("id"):
            raise ValueError("outfit.materials 每一项必须有 id")
        if material["id"] in ids:
            raise ValueError(f"outfit.materials id 重复: {material['id']}")
        ids.add(material["id"])
        if not material.get("refs"):
            raise ValueError(f"材质 {material['id']} 缺少 refs")
        if material.get("role") not in (
                "skin", "hair", "white", "cloth", "eye", "accent", "flat"):
            raise ValueError(f"材质 {material['id']} role 非法")
    validate_garment_layers(template["garment_layers"], materials)
    validate_drawing(template["drawing"], materials)
    return template


def validate_index(index):
    if not isinstance(index, dict):
        raise ValueError("index.json 必须是对象")
    archetypes = index.get("archetypes")
    outfits = index.get("outfits")
    if not isinstance(archetypes, list) or not isinstance(outfits, list):
        raise ValueError("index.json 必须含 archetypes/outfits 列表")
    arch_ids = [item.get("id") for item in archetypes]
    outfit_ids = [item.get("id") for item in outfits]
    if len(set(arch_ids)) != len(arch_ids):
        raise ValueError("index.archetypes id 重复")
    if len(set(outfit_ids)) != len(outfit_ids):
        raise ValueError("index.outfits id 重复")
    for item in archetypes:
        for key in ("id", "name", "ref", "gender", "age_group", "outfits",
                    "keywords"):
            if key not in item:
                raise ValueError(f"index.archetypes 缺少字段: {key}")
        for outfit_id in item["outfits"]:
            if outfit_id not in outfit_ids:
                raise ValueError(f"index 引用了不存在的 outfit: {outfit_id}")
    for item in outfits:
        for key in ("id", "archetype", "type"):
            if key not in item:
                raise ValueError(f"index.outfits 缺少字段: {key}")
        if item["archetype"] not in arch_ids:
            raise ValueError(
                f"index outfit {item['id']} 引用了不存在的原型")
    return index


def load_template(path, templates_dir=None):
    """按文件内容自动识别原型/着装变体，并在索引存在时校验交叉引用。"""
    template = json.loads(Path(path).read_text(encoding="utf-8"))
    if "garment_layers" in template:
        validate_outfit(template)
    elif "body" in template:
        validate_archetype(template)
    else:
        raise ValueError(f"无法识别模板类型: {path}")
    root = Path(templates_dir) if templates_dir else TEMPLATE_ROOT
    index_path = root / "index.json"
    if index_path.exists():
        index = validate_index(
            json.loads(index_path.read_text(encoding="utf-8")))
        if "garment_layers" in template:
            outfit_ids = {item["id"] for item in index["outfits"]}
            if template["id"] not in outfit_ids:
                raise ValueError(f"outfit 未登记到 index: {template['id']}")
        else:
            arch_ids = {item["id"] for item in index["archetypes"]}
            if template["id"] not in arch_ids:
                raise ValueError(f"archetype 未登记到 index: {template['id']}")
    return template


def load(path, templates_dir=None):
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
    validate_body(spec.get("body"))
    validate_garment_layers(spec.get("garment_layers"), spec.get("materials", []))
    validate_template_ref(spec.get("template"), templates_dir)
    validate_drawing(spec.get("drawing"), spec.get("materials", []))
    return spec
