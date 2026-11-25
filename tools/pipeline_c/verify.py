# -*- coding: utf-8 -*-
"""Acceptance checks for a PC-98 tachie PNG.

``check`` returns a list of problems; an empty list means the image passed.
Soft findings are prefixed with ``WARN: `` and must not be treated as errors.
"""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image

SIZE = (640, 400)
DIALOG_Y = 280
_NAME_RE = re.compile(r"[A-Za-z0-9_\-]{1,8}")
_EXT_RE = re.compile(r"[A-Za-z0-9]{1,3}")


def _transparency_problem(image):
    """Verify that the sprite carries a usable transparent background."""
    if image.mode == "P":
        info = image.info.get("transparency")
        if info is None:
            return "indexed PNG has no tRNS chunk; index 0 is not transparent"
        if isinstance(info, (bytes, bytearray)):
            if not info or info[0] != 0:
                return "palette alpha table does not make index 0 transparent"
        elif int(info) != 0:
            return f"PNG declares index {int(info)} as transparent, not index 0"
        return None
    if "A" in image.getbands():
        if image.getchannel("A").getextrema()[0] == 0:
            return None
        return "RGBA PNG has no fully transparent pixel"
    if image.info.get("transparency") is not None:
        return None
    return "image has no palette or alpha channel; index 0 transparency is undefined"


def _occupied_pixels(image):
    """Return the number of sprite pixels inside the y>=DIALOG_Y band."""
    rgba = image.convert("RGBA")
    if rgba.height <= DIALOG_Y:
        return 0
    below = rgba.crop((0, DIALOG_Y, rgba.width, rgba.height))
    transparency = image.info.get("transparency")
    if "A" in image.getbands() or transparency is not None:
        alpha = below.getchannel("A")
        return sum(1 for value in alpha.getdata() if value > 0)
    return sum(1 for pixel in below.getdata()
               if pixel[:3] != (255, 255, 255))


def _unique_colors(image):
    rgba = image.convert("RGBA")
    colors = set()
    for r, g, b, a in rgba.getdata():
        if a:
            colors.add((r, g, b))
    return colors


def check(png_path, max_colors=256, size=SIZE):
    """Return a list of problems (empty = pass); ``WARN:`` items are soft."""
    path = Path(png_path)
    if not path.exists():
        return [f"file not found: {path}"]

    problems = []
    with Image.open(path) as image:
        image.load()
        if image.size != tuple(size):
            problems.append(
                f"size {image.size} != expected {tuple(size)}")

        unique = _unique_colors(image)
        if len(unique) > max_colors:
            problems.append(
                f"{len(unique)} unique colors exceed the {max_colors} limit")

        transparency = _transparency_problem(image)
        if transparency:
            problems.append(transparency)

        below = _occupied_pixels(image)
        if below:
            problems.append(
                f"WARN: {below} sprite pixels occupy the y>={DIALOG_Y} "
                "dialog region")

    stem, ext = path.stem, path.suffix.lstrip(".")
    if not _NAME_RE.fullmatch(stem):
        problems.append(f"filename stem {stem!r} is not DOS 8.3 safe")
    if not _EXT_RE.fullmatch(ext):
        problems.append(f"filename extension {ext!r} is not DOS 8.3 safe")

    return problems
