# -*- coding: utf-8 -*-
"""CLI entry point: ``python -m tools.pipeline_c <command>``."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from tools.pipeline_c import brief as brief_mod
    from tools.pipeline_c import convert as convert_mod
    from tools.pipeline_c import prompt as prompt_mod
    from tools.pipeline_c import verify as verify_mod
except ImportError:
    print("run this CLI from the project root: "
          "python -m tools.pipeline_c <command>", file=sys.stderr)
    raise

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "tools" / "common"
if str(COMMON) not in sys.path:
    sys.path.insert(0, str(COMMON))

import template  # noqa: E402


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cmd_brief(args):
    data = _load_json(args.brief)
    slug = args.slug or data.get("slug") or data.get("id")
    if not slug:
        print("brief needs a slug (pass --slug or set slug/id)", file=sys.stderr)
        return 1
    effective, meta = brief_mod.resolve(data)
    selected = meta["auto_select"]
    if selected:
        print(f"ARCHETYPE: {selected['archetype']}")
        print(f"OUTFIT: {selected['outfit']}")
        print(f"SCORE: {selected['score']}")
    else:
        resolved = meta["resolved_template"]
        print(f"ARCHETYPE: {resolved['archetype']} (pinned)")
        print(f"OUTFIT: {resolved['outfit']} (pinned)")
        print("SCORE: -")
    print("MATCHED: " + (", ".join(meta["matched_keywords"]) or "-"))
    colors = meta.get("colors") or {}
    print("COLORS: applied={} derived={} ignored={}".format(
        ",".join(colors.get("applied", [])) or "-",
        ",".join(colors.get("derived", [])) or "-",
        ",".join(colors.get("ignored", [])) or "-"))
    if colors.get("derived"):
        print("DERIVED: single color -> light/mid/dark "
              "(mid = source, light = brighter & less saturated, "
              "dark = darker & more saturated & cooler hue)")
    out = Path(args.out) if args.out else Path("characters") / slug / "spec.json"
    written = brief_mod.write_spec(effective, out)
    print(f"WROTE: {written}")
    return 0


def cmd_prompt(args):
    spec = _load_json(args.spec)
    effective, _ = brief_mod.resolve_spec(spec)
    print(prompt_mod.build(effective, args.kind))
    return 0


def cmd_convert(args):
    out = convert_mod.to_pc98(
        args.spec, args.src, args.mode, args.out, palette_path=args.palette,
        nose_scale=args.nose_scale, nose_half=args.nose_half)
    print(f"SAVED: {out}")
    return 0


def cmd_verify(args):
    problems = verify_mod.check(args.png, max_colors=args.max_colors)
    for problem in problems:
        print(problem)
    failures = [item for item in problems if not item.startswith("WARN:")]
    if failures:
        print(f"FAIL: {len(failures)} problem(s)", file=sys.stderr)
        return 1
    print("PASS")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m tools.pipeline_c",
        description="Pipeline C: brief -> PC-98 tachie")
    sub = parser.add_subparsers(dest="command", required=True)

    p_brief = sub.add_parser("brief", help="resolve a brief into a spec.json")
    p_brief.add_argument("--brief", required=True, help="brief JSON path")
    p_brief.add_argument("--slug", default="",
                         help="character slug (defaults to brief slug/id)")
    p_brief.add_argument("--out", default="",
                         help="spec output (default characters/<slug>/spec.json)")
    p_brief.set_defaults(func=cmd_brief)

    p_prompt = sub.add_parser("prompt", help="print the image prompt")
    p_prompt.add_argument("--spec", required=True, help="character spec.json")
    p_prompt.add_argument("--kind", default="tachie",
                          choices=("sheet", "tachie", "half", "closeup", "full"))
    p_prompt.set_defaults(func=cmd_prompt)

    p_convert = sub.add_parser("convert", help="HD image -> PC-98 tachie PNG")
    p_convert.add_argument("--spec", required=True, help="character spec.json")
    p_convert.add_argument("--src", required=True, help="HD source image")
    p_convert.add_argument("--mode", required=True,
                           choices=("closeup", "half", "full"))
    p_convert.add_argument("--out", required=True, help="output PNG path")
    p_convert.add_argument("--palette", default="",
                           help="palette98 JSON (defaults to bs.PALETTE)")
    p_convert.add_argument("--nose-scale", type=float,
                           default=convert_mod.NOSE_SCALE_DEFAULT,
                           help="nose diamond scale: 1.0 = source size, "
                                "2.0 = double (default keeps the legacy 2/3)")
    p_convert.add_argument("--nose-half", default="none",
                           choices=("none", "left", "right"),
                           help="clip the diamond to one half (default none)")
    p_convert.set_defaults(func=cmd_convert)

    p_verify = sub.add_parser("verify", help="validate a PC-98 tachie PNG")
    p_verify.add_argument("--png", required=True, help="PNG to check")
    p_verify.add_argument("--max-colors", type=int, default=256)
    p_verify.set_defaults(func=cmd_verify)
    return parser


def main():
    args = build_parser().parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
