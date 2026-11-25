# -*- coding: utf-8 -*-
"""LSP (layered sprite project) core: scene IO, validation and compositing.

The on-disk contract follows the public ``lsp/1`` layout (scene.json + layers/*.png)
with a ``tachie/2`` profile that adds non-exported structure and material-mask
layers.  All image maths stays in float32 to keep 1680x2240 canvases affordable.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

FORMAT = "lsp/1"
PROFILE = "tachie/2"
SCENE = "scene.json"
LAYER_DIR = "layers"
STAGE_FILE = "stages.json"
BLENDS = ("normal", "multiply", "screen", "add", "overlay")
ROLES = ("base", "detail", "shade", "highlight", "lineart", "structure", "mask", "free")
CLIP_DEFAULT = {"shade", "highlight"}
# Downstream layers become stale when an upstream dependency changes.
LAYER_DEPS = {
    "base": [],
    "structure": [],
    "detail": ["base", "structure"],
    "shade": ["base", "structure"],
    "highlight": ["base", "structure"],
    "lineart": ["base", "detail"],
}
STAGE_ORDER = ["base", "structure", "detail", "shade", "highlight", "lineart"]


class LspError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S")


def project_root(path) -> Path:
    root = Path(path).resolve()
    if not root.is_dir():
        raise LspError(f"LSP 目录不存在: {root}")
    return root


def scene_path(root) -> Path:
    return project_root(root) / SCENE


def load_scene(root) -> dict:
    p = scene_path(root)
    if not p.is_file():
        raise LspError(f"缺少 {SCENE}: {p}")
    with p.open(encoding="utf-8") as fh:
        return json.load(fh)


def save_scene(root, scene: dict) -> None:
    p = scene_path(root)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(scene, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def layer_path(root, entry: dict) -> Path:
    rel = entry.get("file")
    if not rel:
        raise LspError(f"图层 {entry.get('id')} 缺少 file")
    root = project_root(root)
    p = (root / rel).resolve()
    if p != root and root not in p.parents:
        raise LspError(f"图层路径越出工程目录: {rel}")
    return p


def load_layer(root, entry: dict, require_file: bool = True) -> Image.Image:
    p = layer_path(root, entry)
    if not p.is_file():
        if require_file:
            raise LspError(f"图层文件不存在: {p}")
        return None
    img = Image.open(p).convert("RGBA")
    return img


def layer_hash(root, entry: dict) -> str:
    p = layer_path(root, entry)
    if not p.is_file():
        return ""
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_scene(root, scene: dict, require_files: bool = False) -> None:
    if scene.get("format") != FORMAT:
        raise LspError(f"format 必须是 {FORMAT!r}，实际 {scene.get('format')!r}")
    if scene.get("profile") != PROFILE:
        raise LspError(f"profile 必须是 {PROFILE!r}，实际 {scene.get('profile')!r}")
    canvas = scene.get("canvas") or {}
    try:
        width, height = int(canvas["width"]), int(canvas["height"])
    except (KeyError, TypeError, ValueError):
        raise LspError("canvas.width/height 缺失或非法")
    if width <= 0 or height <= 0:
        raise LspError("canvas 尺寸必须为正")
    unit = float(scene.get("unit", 0))
    if unit <= 0 or abs(unit - height / 360.0) > max(0.02, height / 360.0 * 0.02):
        raise LspError(f"unit 与 canvas 不一致: unit={unit}, height={height}")
    layers = scene.get("layers") or []
    if not layers:
        raise LspError("layers 为空")
    seen = set()
    roles = {}
    for entry in layers:
        lid = entry.get("id")
        if not lid:
            raise LspError("图层缺少 id")
        if lid in seen:
            raise LspError(f"图层 id 重复: {lid}")
        seen.add(lid)
        role = entry.get("role")
        if role not in ROLES:
            raise LspError(f"图层 {lid} 的 role 非法: {role!r}")
        if entry.get("blend", "normal") not in BLENDS:
            raise LspError(f"图层 {lid} 的 blend 非法: {entry.get('blend')!r}")
        roles.setdefault(role, []).append(entry)
        if role in ("structure", "mask") and entry.get("export", True):
            raise LspError(f"{role} 层必须 export:false: {lid}")
        if require_files:
            img = load_layer(root, entry)
            if img.size != (width, height):
                raise LspError(f"图层 {lid} 尺寸 {img.size} != canvas {(width, height)}")
    for role in ("base", "structure", "mask"):
        if role in roles and len(roles[role]) > 1:
            raise LspError(f"{role} 层只能有一个")
    if "base" not in roles:
        raise LspError("缺少 base 层")
    if not roles["base"][0].get("locked"):
        raise LspError("base 层必须 locked:true")


def _blend_rgb(mode: str, base: np.ndarray, top: np.ndarray) -> np.ndarray:
    if mode == "multiply":
        return base * top
    if mode == "screen":
        return 1.0 - (1.0 - base) * (1.0 - top)
    if mode == "add":
        return np.clip(base + top, 0.0, 1.0)
    if mode == "overlay":
        return np.where(base <= 0.5, 2.0 * base * top,
                        1.0 - 2.0 * (1.0 - base) * (1.0 - top))
    if mode == "normal":
        return top
    raise LspError(f"未知混合模式: {mode}")


def composite(root, scene: dict, include_structure: bool = False) -> Image.Image:
    """Composite exported layers bottom-to-top.  Structure/mask never enter."""
    validate_scene(root, scene, require_files=False)
    width = int(scene["canvas"]["width"])
    height = int(scene["canvas"]["height"])
    out = np.zeros((height, width, 4), np.float32)
    for entry in scene["layers"]:
        if not entry.get("export", True):
            continue
        if not entry.get("visible", True):
            continue
        role = entry["role"]
        if role in ("structure", "mask") and not include_structure:
            continue
        img = load_layer(root, entry)
        if img.size != (width, height):
            raise LspError(f"图层 {entry['id']} 尺寸 {img.size} != {(width, height)}")
        src = np.asarray(img, np.float32) / 255.0
        rgb, alpha = src[..., :3], src[..., 3]
        alpha = alpha * float(entry.get("opacity", 1.0))
        if entry.get("clip", role in CLIP_DEFAULT):
            alpha = alpha * out[..., 3]
        mode = entry.get("blend", "normal")
        if mode == "normal":
            blended = rgb
        else:
            blended = _blend_rgb(mode, out[..., :3], rgb)
            bda = out[..., 3:4]
            blended = blended * bda + rgb * (1.0 - bda)
        a = alpha[..., None]
        out[..., :3] = blended * a + out[..., :3] * (1.0 - a)
        out[..., 3] = alpha + out[..., 3] * (1.0 - alpha)
    return Image.fromarray(np.clip(out * 255.0 + 0.5, 0, 255).astype(np.uint8), "RGBA")


# ---------------------------------------------------------------------------
# Stage ledger


def stage_path(root) -> Path:
    return project_root(root) / STAGE_FILE


def load_stages(root) -> dict:
    p = stage_path(root)
    if not p.is_file():
        return {"order": list(STAGE_ORDER), "stages": {}}
    with p.open(encoding="utf-8") as fh:
        data = json.load(fh)
    data.setdefault("order", list(STAGE_ORDER))
    data.setdefault("stages", {})
    return data


def save_stages(root, data: dict) -> None:
    p = stage_path(root)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def record_stage(root, layer_id: str, scene: dict) -> dict:
    entry = next((e for e in scene["layers"] if e["id"] == layer_id), None)
    if entry is None:
        raise LspError(f"scene 中找不到图层: {layer_id}")
    data = load_stages(root)
    digest = layer_hash(root, entry)
    data["stages"][layer_id] = {
        "sha256": digest,
        "status": "pending",
        "updated": _now(),
    }
    # Any confirmed downstream layer whose dependency changed becomes stale.
    for lid, st in data["stages"].items():
        if lid == layer_id or st.get("status") != "confirmed":
            continue
        if layer_id in LAYER_DEPS.get(lid, []):
            st["status"] = "stale"
    save_stages(root, data)
    return data["stages"][layer_id]


def confirm_stage(root, layer_id: str) -> dict:
    data = load_stages(root)
    st = data["stages"].get(layer_id)
    if not st:
        raise LspError(f"图层 {layer_id} 尚未生成，无法确认")
    st["status"] = "confirmed"
    st["updated"] = _now()
    save_stages(root, data)
    return st


def stage_status(root, scene: dict) -> dict:
    """Refresh hashes and return per-layer status without mutating approval."""
    data = load_stages(root)
    out = {}
    for entry in scene["layers"]:
        lid = entry["id"]
        if lid not in STAGE_ORDER:
            continue
        st = data["stages"].get(lid, {})
        digest = layer_hash(root, entry)
        status = st.get("status", "missing") if digest else "missing"
        if status == "confirmed" and st.get("sha256") != digest:
            status = "stale"
        out[lid] = {"status": status, "sha256": digest,
                    "updated": st.get("updated", "")}
    return out
