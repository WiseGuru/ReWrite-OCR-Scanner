"""Page triage: born_digital / scanned / mixed classification.

The largest speed win in the app: born-digital pages never touch a model.
Some PDFs carry a broken text layer from a prior bad OCR pass, so a present
text layer is not trusted until it passes a sanity check.

All thresholds are named constants here and pinned by tests.
"""

from __future__ import annotations

from rewriteocr.core.models import TriageResult
from rewriteocr.core.pdf_io import PdfDocument

# Below this many characters the text layer is treated as absent.
MIN_TEXT_CHARS = 25
# Sanity: fraction of characters that are printable.
MIN_PRINTABLE_RATIO = 0.95
# Sanity: fraction of non-space characters that are alphanumeric.
MIN_ALNUM_RATIO = 0.50
# Sanity: mean length of whitespace-separated tokens must be plausible.
WORD_LEN_RANGE = (1.5, 15.0)
# Fraction of page area covered by text glyph boxes for born_digital.
MIN_TEXT_AREA_FRAC = 0.02
# Image objects covering at least this fraction of the page, without text
# over them, push the page to mixed.
MIXED_IMAGE_AREA_FRAC = 0.30


def text_sanity(text: str) -> tuple[bool, float, float]:
    """Returns (is_sane, printable_ratio, alnum_ratio)."""
    if not text:
        return False, 0.0, 0.0
    printable = sum(1 for c in text if c.isprintable() or c in "\n\r\t")
    printable_ratio = printable / len(text)
    non_space = [c for c in text if not c.isspace()]
    if not non_space:
        return False, printable_ratio, 0.0
    alnum_ratio = sum(1 for c in non_space if c.isalnum()) / len(non_space)
    words = text.split()
    mean_word_len = sum(len(w) for w in words) / len(words) if words else 0.0
    sane = (
        printable_ratio >= MIN_PRINTABLE_RATIO
        and alnum_ratio >= MIN_ALNUM_RATIO
        and WORD_LEN_RANGE[0] <= mean_word_len <= WORD_LEN_RANGE[1]
    )
    return sane, printable_ratio, alnum_ratio


def _union_area(boxes: list[tuple[float, float, float, float]], grid: int = 64) -> float:
    """Approximate union area of normalized boxes on a coarse grid.
    Exact rectangle union is overkill for a 2 percent threshold."""
    if not boxes:
        return 0.0
    cells = bytearray(grid * grid)
    for x0, y0, x1, y1 in boxes:
        cx0 = max(0, min(grid - 1, int(x0 * grid)))
        cx1 = max(0, min(grid - 1, int(x1 * grid)))
        cy0 = max(0, min(grid - 1, int(y0 * grid)))
        cy1 = max(0, min(grid - 1, int(y1 * grid)))
        for cy in range(cy0, cy1 + 1):
            row = cy * grid
            for cx in range(cx0, cx1 + 1):
                cells[row + cx] = 1
    return sum(cells) / (grid * grid)


def classify_page(doc: PdfDocument, index: int) -> TriageResult:
    text = doc.page_text(index)
    sane, printable_ratio, alnum_ratio = text_sanity(text)

    if len(text.strip()) < MIN_TEXT_CHARS or not sane:
        return TriageResult(
            classification="scanned",
            text=text,
            printable_ratio=printable_ratio,
            alpha_ratio=alnum_ratio,
        )

    glyphs = doc.page_glyphs(index)
    text_boxes = [(g.x0, g.y0, g.x1, g.y1) for g in glyphs if not g.char.isspace()]
    text_area = _union_area(text_boxes)

    image_boxes = doc.page_image_boxes(index)
    # Only count image area not already covered by text glyphs: a scanned
    # page pasted into a born-digital page has no text layer over the scan.
    uncovered_image_area = 0.0
    if image_boxes:
        uncovered_image_area = max(0.0, _union_area(image_boxes + text_boxes) - text_area)

    if text_area < MIN_TEXT_AREA_FRAC:
        classification = "scanned"
    elif uncovered_image_area >= MIXED_IMAGE_AREA_FRAC:
        classification = "mixed"
    else:
        classification = "born_digital"

    return TriageResult(
        classification=classification,
        text=text,
        printable_ratio=printable_ratio,
        alpha_ratio=alnum_ratio,
        text_area_frac=text_area,
        image_area_frac=uncovered_image_area,
    )
