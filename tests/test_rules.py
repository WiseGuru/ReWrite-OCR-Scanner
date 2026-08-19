import pytest

from rewriteocr.core.models import Region
from rewriteocr.core.pdf_io import GlyphBox
from rewriteocr.core.rules import (
    RuleError,
    filter_glyphs_excluding,
    glyphs_to_text,
    parse_range,
    region_applies,
    regions_for_page,
)


def _region(scope, scope_arg=None, kind="exclude", order=0, box=(0.0, 0.0, 1.0, 0.1)):
    return Region(
        scope=scope, scope_arg=scope_arg, kind=kind, order_index=order,
        x0=box[0], y0=box[1], x1=box[2], y1=box[3],
    )


def test_parse_range():
    assert parse_range("12-48") == (12, 48)
    assert parse_range("7") == (7, 7)
    with pytest.raises(RuleError):
        parse_range("48-12")
    with pytest.raises(RuleError):
        parse_range("abc")
    with pytest.raises(RuleError):
        parse_range(None)


def test_odd_even_scoping_uses_book_page_numbers():
    odd = _region("odd")
    even = _region("even")
    # page_index 0 is book page 1: odd.
    assert region_applies(odd, 0)
    assert not region_applies(even, 0)
    assert not region_applies(odd, 1)
    assert region_applies(even, 1)


def test_range_and_single_scoping():
    rng = _region("range", "2-3")
    single = _region("single", "2")
    assert not region_applies(rng, 0)
    assert region_applies(rng, 1)
    assert region_applies(rng, 2)
    assert not region_applies(rng, 3)
    assert region_applies(single, 1)
    assert not region_applies(single, 2)


def test_regions_for_page_sorts_by_order_index():
    r1 = _region("all", order=2)
    r2 = _region("all", order=1)
    assert [r.order_index for r in regions_for_page([r1, r2], 0)] == [1, 2]


def _glyphs_for(text: str, y: float) -> list[GlyphBox]:
    out = []
    x = 0.1
    for ch in text:
        out.append(GlyphBox(char=ch, x0=x, y0=y, x1=x + 0.01, y1=y + 0.02))
        x += 0.012
    return out


def test_exclusion_filters_by_center_point():
    header = _glyphs_for("HEADER", 0.02)
    body = _glyphs_for("Body text", 0.5)
    kept = filter_glyphs_excluding(header + body, [_region("all", box=(0.0, 0.0, 1.0, 0.1))])
    assert all(g.y0 >= 0.4 for g in kept)
    assert len(kept) == len(body)


def test_glyphs_to_text_rebuilds_lines_and_spaces():
    line1 = _glyphs_for("Hello world", 0.10)
    line2 = _glyphs_for("Second line", 0.20)
    text = glyphs_to_text(line1 + line2)
    lines = [ln for ln in text.split("\n") if ln]
    assert lines[0].startswith("Hello")
    assert "world" in lines[0]
    assert lines[-1].startswith("Second")
