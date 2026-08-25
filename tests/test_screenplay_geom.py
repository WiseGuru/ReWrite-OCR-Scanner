"""Born-digital indent oracle.

Column positions are the strongest signal a screenplay has, and they exist as
glyph geometry on born-digital pages. They are re-derived here at export time
from the unmodified source PDF rather than stored, so nothing about the
sidecar schema or the engine contract changes.

Scanned pages get nothing: the VLM returns free-form Markdown and declares
bbox_output false. That is FR-4.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import SCREENPLAY_LINES, make_screenplay_pdf

from rewriteocr.core.models import PageRecord
from rewriteocr.core.pdf_io import PdfDocument
from rewriteocr.core.screenplay import parse_screenplay
from rewriteocr.core.screenplay_geom import line_indents
from rewriteocr.core.sidecar import SidecarDB

EXPECTED_TYPES = [kind for kind, _ in SCREENPLAY_LINES]


def _project(tmp_path, pdf: Path, classification: str = "born_digital"):
    """A sidecar whose page text is the PDF's own, which is what extraction
    stores for a born-digital page with no regions."""
    db = SidecarDB(tmp_path / "s.ocrproj")
    db.initialize("h", pdf.name, 1)
    with PdfDocument(pdf) as doc:
        w, h = doc.page_size_pt(0)
        text = doc.page_text(0).replace("\r\n", "\n").replace("\r", "\n")
    db.insert_pages(
        [PageRecord(page_index=0, classification=classification, width_pt=w, height_pt=h)]
    )
    db.write_page_result(0, text, "text_layer", None, None, [])
    return db, [text]


def test_indents_are_recovered_in_inches(tmp_path, screenplay_pdf):
    db, pages = _project(tmp_path, screenplay_pdf)
    indents = line_indents(db, screenplay_pdf, pages)
    db.close()
    assert indents is not None
    found = [v for v in indents[0] if v is not None]
    assert found, "no line aligned"
    # The scene heading and action sit at 1.5in, the character cue at 3.7in.
    assert min(found) == pytest.approx(1.5, abs=0.1)
    assert max(found) == pytest.approx(5.5, abs=0.1)


def test_geometry_classifies_the_whole_page(tmp_path, screenplay_pdf):
    db, pages = _project(tmp_path, screenplay_pdf)
    indents = line_indents(db, screenplay_pdf, pages)
    db.close()
    script = parse_screenplay(pages, indents=indents)
    assert [el.type for el in script.elements] == EXPECTED_TYPES
    assert script.report.geometry_pages == 1


def test_a_shifted_left_margin_still_classifies(tmp_path):
    """Offsets are measured from the document's own action margin, so a
    script printed or scanned off-centre must classify identically."""
    pdf = make_screenplay_pdf(tmp_path / "shifted.pdf", left_margin_in=0.75)
    db, pages = _project(tmp_path, pdf)
    indents = line_indents(db, pdf, pages)
    db.close()
    assert indents is not None
    script = parse_screenplay(pages, indents=indents)
    assert [el.type for el in script.elements] == EXPECTED_TYPES


def test_edited_text_disables_geometry(tmp_path, screenplay_pdf):
    # A user edit invalidates the mapping from glyphs to text, so the page
    # falls back to lexical classification rather than mis-aligning.
    db, pages = _project(tmp_path, screenplay_pdf)
    db.set_edited_text(0, pages[0])
    indents = line_indents(db, screenplay_pdf, pages)
    db.close()
    assert indents is None


def test_scanned_pages_get_no_geometry(tmp_path, screenplay_pdf):
    db, pages = _project(tmp_path, screenplay_pdf, classification="scanned")
    indents = line_indents(db, screenplay_pdf, pages)
    db.close()
    assert indents is None


def test_missing_pdf_degrades_to_lexical(tmp_path, screenplay_pdf):
    db, pages = _project(tmp_path, screenplay_pdf)
    assert line_indents(db, None, pages) is None
    assert line_indents(db, tmp_path / "gone.pdf", pages) is None
    db.close()
    # And the classifier still works with no indents at all.
    assert [el.type for el in parse_screenplay(pages).elements] == EXPECTED_TYPES


def test_unrelated_pdf_does_not_produce_bogus_indents(tmp_path, screenplay_pdf,
                                                      born_digital_pdf):
    """Alignment is by text, so pointing at the wrong PDF yields no match
    rather than indents attached to the wrong lines."""
    db, pages = _project(tmp_path, screenplay_pdf)
    indents = line_indents(db, born_digital_pdf, pages)
    db.close()
    assert indents is None
