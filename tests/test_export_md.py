from rewriteocr.core.models import ExportOptions, PageRecord
from rewriteocr.core.sidecar import SidecarDB
from rewriteocr.pipeline.export_md import (
    PAGE_BREAK_COMMENT,
    assemble_markdown,
    export_markdown,
)


def _sidecar_with_pages(tmp_path, texts):
    db = SidecarDB(tmp_path / "x.ocrproj")
    db.initialize("h", "x.pdf", len(texts))
    db.insert_pages(
        [PageRecord(page_index=i, classification="scanned", width_pt=612, height_pt=792)
         for i in range(len(texts))]
    )
    for i, t in enumerate(texts):
        db.write_page_result(i, t, "vlm:m", "m", "r", [])
    return db


def test_assemble_page_break_options():
    pages = ["Page one.", "Page two."]
    none, _ = assemble_markdown(pages, ExportOptions(page_break="none", stitch=False))
    assert PAGE_BREAK_COMMENT not in none and "---" not in none
    comment, _ = assemble_markdown(pages, ExportOptions(page_break="comment", stitch=False))
    assert PAGE_BREAK_COMMENT in comment
    rule, _ = assemble_markdown(pages, ExportOptions(page_break="rule", stitch=False))
    assert "\n---\n" in rule


def test_empty_pages_skipped():
    md, _ = assemble_markdown(["One.", "", "Three."], ExportOptions(stitch=False))
    assert md == "One.\n\nThree.\n"


def test_edited_text_wins_in_export(tmp_path):
    db = _sidecar_with_pages(tmp_path, ["engine text"])
    db.set_edited_text(0, "edited text")
    out = tmp_path / "out.md"
    export_markdown(db, out, ExportOptions(stitch=False))
    assert out.read_text(encoding="utf-8") == "edited text\n"
    db.close()


def test_figures_copied_and_refs_rewritten(tmp_path):
    db = _sidecar_with_pages(tmp_path, ["Before\n\n![Figure](x_figures/page0001_fig01.png)"])
    figdir = tmp_path / "x_figures"
    figdir.mkdir()
    (figdir / "page0001_fig01.png").write_bytes(b"fakepng")
    out = tmp_path / "exported" / "book.md"
    export_markdown(db, out, ExportOptions(stitch=False))
    text = out.read_text(encoding="utf-8")
    assert "](book_figures/page0001_fig01.png)" in text
    assert (tmp_path / "exported" / "book_figures" / "page0001_fig01.png").is_file()
    db.close()


def test_stitching_applied_in_export():
    pages = ["Ends with hyphen-", "ated word here."]
    md, log = assemble_markdown(pages, ExportOptions(stitch=True))
    assert "hyphenated" in md
    assert log.hyphen_joins
