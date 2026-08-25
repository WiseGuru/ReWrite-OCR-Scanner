"""Region scope resolution and geometric text-layer filtering.

Scopes use 1-based book page numbers for odd/even/range/single because that
is how users think about pages; page_index is 0-based internally, so index 0
is page 1, an odd page.
"""

from __future__ import annotations

import statistics

from rewriteocr.core.models import Region
from rewriteocr.core.pdf_io import GlyphBox


class RuleError(Exception):
    pass


def parse_range(scope_arg: str | None) -> tuple[int, int]:
    """'12-48' -> (12, 48); '7' -> (7, 7). 1-based inclusive."""
    if not scope_arg:
        raise RuleError("Range scope requires an argument like '12-48'.")
    part = scope_arg.strip()
    if "-" in part:
        lo, _, hi = part.partition("-")
        try:
            start, end = int(lo), int(hi)
        except ValueError as exc:
            raise RuleError(f"Bad range '{scope_arg}'.") from exc
    else:
        try:
            start = end = int(part)
        except ValueError as exc:
            raise RuleError(f"Bad page number '{scope_arg}'.") from exc
    if start < 1 or end < start:
        raise RuleError(f"Bad range '{scope_arg}'.")
    return start, end


def region_applies(region: Region, page_index: int) -> bool:
    page_no = page_index + 1
    if region.scope == "all":
        return True
    if region.scope == "odd":
        return page_no % 2 == 1
    if region.scope == "even":
        return page_no % 2 == 0
    if region.scope == "range":
        start, end = parse_range(region.scope_arg)
        return start <= page_no <= end
    if region.scope == "single":
        start, end = parse_range(region.scope_arg)
        return page_no == start
    raise RuleError(f"Unknown scope '{region.scope}'.")


def regions_for_page(regions: list[Region], page_index: int) -> list[Region]:
    hits = [r.normalized() for r in regions if region_applies(r, page_index)]
    hits.sort(key=lambda r: (r.order_index, r.id or 0))
    return hits


def _center_in(g: GlyphBox, region: Region) -> bool:
    cx = (g.x0 + g.x1) / 2
    cy = (g.y0 + g.y1) / 2
    return region.x0 <= cx <= region.x1 and region.y0 <= cy <= region.y1


def filter_glyphs_excluding(glyphs: list[GlyphBox], regions: list[Region]) -> list[GlyphBox]:
    """Drop glyphs whose center falls in any exclude region."""
    excludes = [r for r in regions if r.kind == "exclude"]
    if not excludes:
        return glyphs
    return [g for g in glyphs if not any(_center_in(g, r) for r in excludes)]


def glyphs_in_region(glyphs: list[GlyphBox], region: Region) -> list[GlyphBox]:
    return [g for g in glyphs if _center_in(g, region)]


def bin_glyph_lines(glyphs: list[GlyphBox]) -> tuple[list[list[GlyphBox]], float]:
    """Bin inked glyphs into text lines by vertical center, top to bottom.

    Returns the lines and the median glyph height, which callers use as the
    scale for vertical-gap decisions. Shared by glyphs_to_text and by the
    screenplay indent oracle, which needs the same line segmentation.
    """
    inked = [g for g in glyphs if g.char and not g.char.isspace()]
    if not inked:
        return [], 0.01
    heights = [g.y1 - g.y0 for g in inked]
    med_h = statistics.median(heights) or 0.01

    inked.sort(key=lambda g: ((g.y0 + g.y1) / 2, g.x0))
    lines: list[list[GlyphBox]] = []
    current: list[GlyphBox] = [inked[0]]
    current_cy = (inked[0].y0 + inked[0].y1) / 2
    for g in inked[1:]:
        cy = (g.y0 + g.y1) / 2
        if abs(cy - current_cy) <= med_h * 0.6:
            current.append(g)
            n = len(current)
            current_cy = current_cy + (cy - current_cy) / n
        else:
            lines.append(current)
            current = [g]
            current_cy = cy
    lines.append(current)
    return lines, med_h


def glyphs_to_text(glyphs: list[GlyphBox]) -> str:
    """Rebuild reading text from glyph geometry: bin into lines by vertical
    center, order by x, insert spaces on horizontal gaps and paragraph breaks
    on large vertical gaps. Used only when geometry filtering changed the
    glyph set; untouched pages keep the PDF's own text order."""
    lines, med_h = bin_glyph_lines(glyphs)
    if not lines:
        return ""
    inked = [g for line in lines for g in line]

    widths = [g.x1 - g.x0 for g in inked if g.x1 > g.x0]
    med_w = statistics.median(widths) if widths else 0.005

    out_lines: list[str] = []
    prev_bottom: float | None = None
    for line in lines:
        line.sort(key=lambda g: g.x0)
        parts: list[str] = []
        prev_x1: float | None = None
        for g in line:
            if prev_x1 is not None and g.x0 - prev_x1 > med_w * 0.45:
                parts.append(" ")
            parts.append(g.char)
            prev_x1 = max(prev_x1 or g.x1, g.x1)
        top = min(g.y0 for g in line)
        if prev_bottom is not None and top - prev_bottom > med_h * 1.2:
            out_lines.append("")
        out_lines.append("".join(parts))
        prev_bottom = max(g.y1 for g in line)
    return "\n".join(out_lines).strip()
