"""Normalize engine output to canonical Markdown.

Dedicated OCR models emit Markdown directly; this pass only removes wrapper
artifacts and whitespace noise. It must never rewrite content.
"""

from __future__ import annotations

import re

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍﻿"))
_FENCE_RE = re.compile(r"\A```[a-zA-Z]*\s*\n(.*)\n```\s*\Z", re.DOTALL)
_HEADING_RE = re.compile(r"^(#{1,6})([^#\s])", re.MULTILINE)


def normalize_markdown(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.translate(_ZERO_WIDTH)
    # Unwrap a single fence around the entire output (```markdown ... ```).
    m = _FENCE_RE.match(text.strip())
    if m:
        text = m.group(1)
    # Ensure a space after heading hashes.
    text = _HEADING_RE.sub(r"\1 \2", text)
    # Strip trailing whitespace per line, collapse runs of blank lines.
    lines = [ln.rstrip() for ln in text.split("\n")]
    out: list[str] = []
    blank = False
    for ln in lines:
        if ln == "":
            if not blank and out:
                out.append("")
            blank = True
        else:
            out.append(ln)
            blank = False
    return "\n".join(out).strip()
