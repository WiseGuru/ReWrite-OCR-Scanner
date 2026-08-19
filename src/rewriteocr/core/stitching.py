"""Cross-page stitching, applied at export time only. The sidecar's per-page
text is never rewritten by these; they operate on a copy of the page list.

Order matters: running headers are dropped first (so a header between a
table and its continuation does not block the merge), then tables merge,
then hyphenated words rejoin.
"""

from __future__ import annotations

import re

from rewriteocr.core.models import StitchLog

# A line appearing at the same position on more than this fraction of pages
# is treated as a running header or footer.
RUNNING_HEADER_FRACTION = 0.60
# Do not hunt for running headers in tiny documents.
MIN_PAGES_FOR_HEADER_DETECTION = 5

_WS = re.compile(r"\s+")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEPARATOR = re.compile(r"^\s*\|(\s*:?-+:?\s*\|)+\s*$")
_HYPHEN_END = re.compile(r"(\w)-\s*$")


def _normalize_header_line(line: str) -> str:
    """Whitespace-collapsed lowercase. Lines that are only a page number
    (digits and punctuation) collapse to one sentinel so numbering does not
    defeat the repeat count; other digits are kept so distinct numbered
    headings ('Section 1', 'Section 2') never collide."""
    stripped = line.strip()
    if stripped and not re.sub(r"[\d\s.\-,()\[\]]+", "", stripped):
        return "<pagenum>"
    return _WS.sub(" ", stripped.lower())


def drop_running_headers(pages: list[str], log: StitchLog) -> list[str]:
    if len([p for p in pages if p.strip()]) < MIN_PAGES_FOR_HEADER_DETECTION:
        return pages
    first_counts: dict[str, int] = {}
    last_counts: dict[str, int] = {}
    nonempty = 0
    for text in pages:
        lines = [ln for ln in text.split("\n") if ln.strip()]
        if not lines:
            continue
        nonempty += 1
        first_counts[_normalize_header_line(lines[0])] = (
            first_counts.get(_normalize_header_line(lines[0]), 0) + 1
        )
        last_counts[_normalize_header_line(lines[-1])] = (
            last_counts.get(_normalize_header_line(lines[-1]), 0) + 1
        )
    threshold = nonempty * RUNNING_HEADER_FRACTION
    drop_first = {k for k, v in first_counts.items() if v > threshold}
    drop_last = {k for k, v in last_counts.items() if v > threshold}
    if not drop_first and not drop_last:
        return pages

    out = []
    for text in pages:
        lines = text.split("\n")
        idx_nonblank = [i for i, ln in enumerate(lines) if ln.strip()]
        to_delete = set()
        if idx_nonblank:
            first_i, last_i = idx_nonblank[0], idx_nonblank[-1]
            first_key = _normalize_header_line(lines[first_i])
            last_key = _normalize_header_line(lines[last_i])
            if first_key in drop_first:
                to_delete.add(first_i)
                if first_key not in log.headers_dropped:
                    log.headers_dropped.append(first_key)
            if last_i != first_i and last_key in drop_last:
                to_delete.add(last_i)
                if last_key not in log.headers_dropped:
                    log.headers_dropped.append(last_key)
        out.append(
            "\n".join(ln for i, ln in enumerate(lines) if i not in to_delete).strip()
        )
    return out


def _trailing_table(text: str) -> tuple[str, list[str]]:
    """Split text into (rest, trailing pipe-table lines)."""
    lines = text.rstrip().split("\n")
    i = len(lines)
    while i > 0 and _TABLE_ROW.match(lines[i - 1]):
        i -= 1
    return "\n".join(lines[:i]).rstrip(), lines[i:]


def _leading_table(text: str) -> tuple[list[str], str]:
    lines = text.lstrip().split("\n")
    i = 0
    while i < len(lines) and _TABLE_ROW.match(lines[i]):
        i += 1
    return lines[:i], "\n".join(lines[i:]).lstrip()


def _column_count(row: str) -> int:
    return len([c for c in row.strip().strip("|").split("|")])


def merge_continued_tables(pages: list[str], log: StitchLog) -> list[str]:
    out = list(pages)
    for i in range(len(out) - 1):
        if not out[i] or not out[i + 1]:
            continue
        rest, tail_table = _trailing_table(out[i])
        if len(tail_table) < 2:
            continue
        head_table, remainder = _leading_table(out[i + 1])
        if not head_table:
            continue
        # A continuation has no header: its second line is not a separator row.
        if len(head_table) > 1 and _TABLE_SEPARATOR.match(head_table[1]):
            continue
        if _TABLE_SEPARATOR.match(head_table[0]):
            continue
        if _column_count(head_table[0]) != _column_count(tail_table[-1]):
            continue
        out[i] = (rest + "\n" + "\n".join(tail_table + head_table)).strip()
        out[i + 1] = remainder
        log.tables_merged.append(i)
    return out


def rejoin_hyphenation(pages: list[str], log: StitchLog) -> list[str]:
    out = list(pages)
    for i in range(len(out) - 1):
        if not out[i] or not out[i + 1]:
            continue
        m = _HYPHEN_END.search(out[i])
        if not m:
            continue
        nxt = out[i + 1].lstrip()
        if not nxt or not nxt[0].islower():
            continue
        first_word_match = re.match(r"([\w']+)", nxt)
        if not first_word_match:
            continue
        first_word = first_word_match.group(1)
        out[i] = _HYPHEN_END.sub(r"\1" + first_word, out[i])
        out[i + 1] = nxt[len(first_word):].lstrip()
        log.hyphen_joins.append(i)
    return out


def stitch_pages(pages: list[str]) -> tuple[list[str], StitchLog]:
    log = StitchLog()
    pages = drop_running_headers(pages, log)
    pages = merge_continued_tables(pages, log)
    pages = rejoin_hyphenation(pages, log)
    return pages, log
