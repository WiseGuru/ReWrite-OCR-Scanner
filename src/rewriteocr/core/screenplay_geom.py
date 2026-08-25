"""Born-digital indent oracle for the screenplay classifier.

A screenplay encodes its element types in column positions: action at the
left margin, dialogue about an inch in, the character cue about two. Those
positions exist as glyph geometry on born-digital pages and are thrown away
during extraction, because the exported text is Markdown and leading
indentation in Markdown is a code block.

Rather than change what is stored, the geometry is re-derived here at export
time from the unmodified source PDF and aligned back onto the canonical
text. Nothing is persisted and no schema changes.

Scanned pages get nothing: the VLM returns free-form Markdown, declares
bbox_output false, and its text was never aligned to Tesseract's line boxes.
That is FR-4, not this module.
"""

from __future__ import annotations

import difflib
import logging
import re
from pathlib import Path

from rewriteocr.core.pdf_io import PdfDocument
from rewriteocr.core.rules import bin_glyph_lines
from rewriteocr.core.sidecar import SidecarDB

log = logging.getLogger(__name__)

_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")

# Below this ratio of matched lines the alignment is not trustworthy and the
# whole page falls back to lexical classification.
MIN_MATCH_RATIO = 0.5


def _key(s: str) -> str:
    """Comparison key for aligning a glyph line against a text line. Case and
    punctuation are dropped because glyph rebuilding and PDFium's own text
    order differ on spacing and soft hyphens, never on letters."""
    return _NORMALIZE_RE.sub("", s.lower())


def line_indents(
    sidecar: SidecarDB, pdf_path: Path | None, pages: list[str]
) -> list[list[float | None]] | None:
    """Per page, per line of `pages`, inches from the page's left edge.

    `pages` must be the same post-stitch text the classifier will see, so the
    alignment lands on the right line numbers. Returns None when no page
    yielded geometry at all, and None entries for lines that did not align.
    """
    if pdf_path is None or not Path(pdf_path).exists():
        return None

    records = {p.page_index: p for p in sidecar.get_pages()}
    out: list[list[float | None]] = [[None] * len(page.split("\n")) for page in pages]
    any_geometry = False

    try:
        with PdfDocument(pdf_path) as doc:
            for page_index, page_text in enumerate(pages):
                record = records.get(page_index)
                if record is None or record.classification != "born_digital":
                    continue
                # A user edit invalidates the mapping from glyphs to text.
                if record.edited_text is not None:
                    continue
                if page_index >= doc.page_count:
                    continue
                try:
                    indents = _page_indents(doc, page_index, record, page_text)
                except Exception:
                    log.exception("Indent oracle failed on page %d", page_index)
                    continue
                if indents is not None:
                    out[page_index] = indents
                    any_geometry = True
    except Exception:
        # The source PDF may have moved, been replaced, or be unreadable.
        # Geometry is a bonus; never fail an export over it.
        log.exception("Indent oracle could not open %s", pdf_path)
        return None

    return out if any_geometry else None


def _page_indents(
    doc: PdfDocument, page_index: int, record, page_text: str
) -> list[float | None] | None:
    glyphs = doc.page_glyphs(page_index)
    if not glyphs:
        return None
    glyph_lines, _ = bin_glyph_lines(glyphs)
    if not glyph_lines:
        return None

    width_pt = record.width_pt
    if record.rotation in (90, 270):
        width_pt = record.height_pt
    if not width_pt:
        return None

    glyph_text: list[str] = []
    glyph_indent: list[float] = []
    for line in glyph_lines:
        line = sorted(line, key=lambda g: g.x0)
        glyph_text.append("".join(g.char for g in line))
        glyph_indent.append(min(g.x0 for g in line) * width_pt / 72.0)

    text_lines = page_text.split("\n")
    indents: list[float | None] = [None] * len(text_lines)

    matcher = difflib.SequenceMatcher(
        a=[_key(s) for s in glyph_text],
        b=[_key(s) for s in text_lines],
        autojunk=False,
    )
    matched = 0
    for gi, ti, size in matcher.get_matching_blocks():
        for offset in range(size):
            if not _key(text_lines[ti + offset]):
                continue
            indents[ti + offset] = glyph_indent[gi + offset]
            matched += 1

    nonempty = sum(1 for s in text_lines if _key(s))
    if not nonempty or matched / nonempty < MIN_MATCH_RATIO:
        return None
    return indents
