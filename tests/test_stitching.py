from rewriteocr.core.models import StitchLog
from rewriteocr.core.stitching import (
    drop_running_headers,
    merge_continued_tables,
    rejoin_hyphenation,
    stitch_pages,
)


def _pages_with_headers(n=8):
    return [
        f"A History of Fixtures\n\nBody paragraph of page {i + 1}.\n\n{i + 1}"
        for i in range(n)
    ]


def test_running_headers_and_page_numbers_dropped():
    pages, log = stitch_pages(_pages_with_headers())
    for p in pages:
        assert "History of Fixtures" not in p
        lines = [ln for ln in p.split("\n") if ln.strip()]
        assert not lines[-1].strip().isdigit()
    assert log.headers_dropped


def test_headers_kept_in_small_documents():
    pages = _pages_with_headers(3)
    out = drop_running_headers(list(pages), StitchLog())
    assert out == pages


def test_unique_first_lines_are_kept():
    pages = [f"Unique heading {i}\n\nBody {i}." for i in range(10)]
    out = drop_running_headers(list(pages), StitchLog())
    assert out == pages


def test_hyphen_rejoin():
    log = StitchLog()
    pages = rejoin_hyphenation(
        ["Some text ending in exam-", "ple of a continuation here."], log
    )
    assert pages[0].endswith("example")
    assert pages[1].startswith("of a continuation")
    assert log.hyphen_joins == [0]


def test_hyphen_not_joined_before_uppercase():
    log = StitchLog()
    pages = rejoin_hyphenation(["Vitamin B-", "Complex is different."], log)
    assert pages[0].endswith("B-")
    assert log.hyphen_joins == []


def test_table_continuation_merges():
    log = StitchLog()
    p1 = "Intro text.\n\n| A | B |\n| --- | --- |\n| 1 | 2 |"
    p2 = "| 3 | 4 |\n| 5 | 6 |\n\nAfter the table."
    pages = merge_continued_tables([p1, p2], log)
    assert "| 5 | 6 |" in pages[0]
    assert pages[1] == "After the table."
    assert log.tables_merged == [0]


def test_table_with_header_row_not_merged():
    log = StitchLog()
    p1 = "| A | B |\n| --- | --- |\n| 1 | 2 |"
    p2 = "| X | Y |\n| --- | --- |\n| 9 | 8 |"
    pages = merge_continued_tables([p1, p2], log)
    assert pages[1].startswith("| X |")
    assert log.tables_merged == []


def test_table_column_mismatch_not_merged():
    log = StitchLog()
    p1 = "| A | B |\n| --- | --- |\n| 1 | 2 |"
    p2 = "| 1 | 2 | 3 |"
    pages = merge_continued_tables([p1, p2], log)
    assert pages[1] == p2
    assert log.tables_merged == []
