# -*- coding: utf-8 -*-
"""Global art direction shared by every prompt builder in the project.

The keywords live in ``STYLE_KEYWORDS.md`` at the repo root (single source of
truth, must be read before any image generation).  This module loads that file
at import time and fails loudly if the file or any required credit is missing.
"""
from __future__ import annotations

from pathlib import Path

KEYWORDS_PATH = Path(__file__).resolve().parents[2] / "STYLE_KEYWORDS.md"


def _load_keywords(path=KEYWORDS_PATH):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError(f"cannot read mandatory style keywords: {path}") from exc
    credit = ""
    required = []
    swim = []
    body = []
    face = []
    for line in lines:
        text = line.strip()
        if text.startswith("CREDIT:"):
            credit = text.split(":", 1)[1].strip()
        elif text.startswith("REQUIRED:"):
            required.append(text.split(":", 1)[1].strip())
        elif text.startswith("SWIM_REQUIRED:"):
            swim.append(text.split(":", 1)[1].strip())
        elif text.startswith("BODY_REQUIRED:"):
            body.append(text.split(":", 1)[1].strip())
        elif text.startswith("FACE_REQUIRED:"):
            face.append(text.split(":", 1)[1].strip())
    if not credit:
        raise RuntimeError(f"no CREDIT line in {path}")
    if not required:
        raise RuntimeError(f"no REQUIRED lines in {path}")
    if not face:
        raise RuntimeError(f"no FACE_REQUIRED lines in {path}")
    for name in required:
        if name not in credit:
            raise RuntimeError(
                f"required credit {name!r} missing from CREDIT in {path}")
    return credit, tuple(required), tuple(swim), tuple(body), tuple(face)


STYLE_CREDIT, MANDATORY_CREDITS, SWIM_CLAUSE, BODY_CLAUSE, FACE_CLAUSE = _load_keywords()


def swimwear_clause():
    """Return the mandatory extra clauses for swimwear prompts."""
    if not SWIM_CLAUSE:
        raise RuntimeError(f"no SWIM_REQUIRED lines in {KEYWORDS_PATH}")
    return " ".join(SWIM_CLAUSE)


def body_clause():
    """Return the mandatory body-proportion clauses shared by every prompt."""
    if not BODY_CLAUSE:
        raise RuntimeError(f"no BODY_REQUIRED lines in {KEYWORDS_PATH}")
    return " ".join(BODY_CLAUSE)


def face_clause():
    """Return the mandatory facial-feature clauses shared by every prompt."""
    if not FACE_CLAUSE:
        raise RuntimeError(f"no FACE_REQUIRED lines in {KEYWORDS_PATH}")
    return " ".join(FACE_CLAUSE)


def with_credit(style):
    """Return ``style`` prefixed with the mandatory global credit block."""
    text = f"{STYLE_CREDIT}, {body_clause()}, {face_clause()}, {style}"
    for credit in MANDATORY_CREDITS:
        if credit not in text:
            raise RuntimeError(f"mandatory style credit missing: {credit}")
    return text
