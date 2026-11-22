"""按角色 spec 的 materials 生成 16 色板（色板属于角色）。

规则（docs/10）：
- 总数 16，黑色与白色强制保留；
- 不再强制 12 核心色：从 CORE + FLEX 池中按材质参考色覆盖度选 16 槽；
- 未被材质需要的槽位让位给角色实际颜色。

用法：
    python tools/common/palette_for.py --spec characters/momo/spec.json \
        --out characters/momo/palette.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "common"))
import palette98  # noqa: E402

TOTAL = 16
MANDATORY = ("black", "white")


def _hex_rgb(s: str) -> np.ndarray:
    s = s.lstrip("#")
    return np.array([int(s[i:i + 2], 16) for i in (0, 2, 4)], np.float32)


def _lab(rgb: np.ndarray) -> np.ndarray:
    c = rgb / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124, 0.3576, 0.1805],
                  [0.2126, 0.7152, 0.0722],
                  [0.0193, 0.1192, 0.9505]], np.float32)
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883], np.float32)
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16,
                     500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])], -1)


def _refs(spec: dict) -> list[np.ndarray]:
    out = []
    for m in spec.get("materials", []):
        out.extend(_hex_rgb(h) for h in m.get("refs", []))
    if not out:
        for group in spec.get("palette", {}).values():
            out.extend(_hex_rgb(h) for h in group)
    return out


def _score(ref_lab: np.ndarray, cols_lab: np.ndarray) -> float:
    d = ((ref_lab[:, None, :] - cols_lab[None, :, :]) ** 2).sum(-1)
    return float(np.sqrt(d.min(1)).sum())


def _quantize_ref(ref: str) -> tuple[str, np.ndarray]:
    q = (np.round(_hex_rgb(ref) / 17.0) * 17).clip(0, 255).astype(int)
    key = tuple(int(v) for v in q)
    name = ("black" if key == (0, 0, 0)
            else "white" if key == (255, 255, 255)
            else "ref_%02x%02x%02x" % key)
    return name, q.astype(np.float32)


def build_palette(spec: dict) -> dict:
    refs = _refs(spec)
    if not refs:
        raise ValueError("spec 里没有 materials.refs")

    # 材质参考色先量化为 4bit 槽（RGB 取 17 的倍数），作为角色主色。
    # 这样皮肤/头发/布料的每个色阶都有独立槽位，不会被别的材质抢走（docs/10 §2.4）。
    slots: list[tuple[str, np.ndarray]] = []
    for r in refs:
        # 参考色正好是纯黑/纯白时并到强制槽，避免占两个槽。
        name, q = _quantize_ref("#%02x%02x%02x" % tuple(int(v) for v in r))
        if all(n != name for n, _ in slots):
            slots.append((name, q))
    base = {
        "black": np.zeros(3, np.float32),
        "white": np.full(3, 255.0, np.float32),
    }
    for name in MANDATORY:
        if all(n != name for n, _ in slots):
            slots.insert(0, (name, base[name]))

    # 记录每个槽的全部用途；被皮肤/头发/眼睛或暗部复用的槽禁止自动删除。
    slot_uses: dict[str, list[dict]] = {}
    for m in spec.get("materials", []):
        for ref_i, h in enumerate(m.get("refs", [])):
            name, _ = _quantize_ref(h)
            slot_uses.setdefault(name, []).append({
                "role": m.get("role", "flat"),
                "group": m.get("group"),
                "ref_index": ref_i,
            })
    aliases = {}

    def mergeable(name):
        uses = slot_uses.get(name, [])
        return bool(uses) and all(
            u["role"] == "cloth" and u["ref_index"] == 0 and u["group"]
            for u in uses)

    def _merge_same_group_cloth(slots):
        labs = _lab(np.array([v for _, v in slots]))
        d = ((labs[:, None, :] - labs[None, :, :]) ** 2).sum(-1)
        best = None
        for i in range(len(slots)):
            for j in range(i + 1, len(slots)):
                ni, nj = slots[i][0], slots[j][0]
                if not mergeable(ni) or not mergeable(nj):
                    continue
                gi = {u["group"] for u in slot_uses[ni]}
                gj = {u["group"] for u in slot_uses[nj]}
                if not gi & gj:
                    continue
                if best is None or d[i, j] < best[0]:
                    best = (d[i, j], i, j)
        if best is None:
            return None
        _, i, j = best
        aliases[slots[j][0]] = slots[i][0]
        return [s for k, s in enumerate(slots) if k != j]

    while len(slots) > TOTAL:
        merged = _merge_same_group_cloth(slots)
        if merged is None:
            raise ValueError(
                f"色板需要 {len(slots)} 槽，超过 {TOTAL}；"
                "没有可自动合并的同组布料主色，请人工评审")
        slots = merged

    # 不足 16 色时，从 CORE/FLEX 池里按参考色覆盖度补齐
    pool: dict[str, np.ndarray] = {
        n: np.array(v, np.float32) for n, v in palette98.CORE.items()}
    for n, v in palette98.FLEX.items():
        pool.setdefault(n, np.array(v, np.float32))

    ref_lab = _lab(np.array(refs))
    cur_lab = _lab(np.array([v for _, v in slots]))
    while len(slots) < TOTAL:
        best_name, best_score = None, _score(ref_lab, cur_lab)
        for n, rgb in pool.items():
            if any(n == s for s, _ in slots):
                continue
            s = _score(ref_lab, np.vstack([cur_lab, _lab(rgb[None, :])]))
            if s < best_score - 1e-9:
                best_name, best_score = n, s
        if best_name is None:
            break
        slots.append((best_name, pool[best_name]))
        cur_lab = _lab(np.array([v for _, v in slots]))

    chosen = [n for n, _ in slots]
    colors = [list(map(int, v)) for _, v in slots]
    colors = [list(t) for t in dict.fromkeys(tuple(c) for c in colors)]

    def final_slot(name):
        while name in aliases:
            name = aliases[name]
        return name

    mapping = {}
    for m in spec.get("materials", []):
        mapping[m["id"]] = {}
        for h in m.get("refs", []):
            name, _ = _quantize_ref(h)
            slot = final_slot(name)
            if slot not in chosen:
                raise RuntimeError(f"参考色 {h} 没有最终色板槽位")
            mapping[m["id"]][h] = slot

    return {
        "character": spec.get("id", "?"),
        "count": len(colors),
        "colors": colors,
        "slots": chosen,
        "roles": {m["id"]: m.get("refs", []) for m in spec.get("materials", [])},
        "mapping": mapping,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    try:
        payload = build_palette(spec)
    except ValueError as exc:
        sys.exit(str(exc))
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"colors={payload['count']} -> {target}")
    print("slots:", ", ".join(payload["slots"]))


if __name__ == "__main__":
    main()
