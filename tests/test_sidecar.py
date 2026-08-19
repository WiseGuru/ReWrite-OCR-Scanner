import pytest

from rewriteocr.core.models import Flag, PageRecord, Region
from rewriteocr.core.sidecar import SidecarDB, SidecarError


@pytest.fixture
def db(tmp_path):
    db = SidecarDB(tmp_path / "test.ocrproj")
    db.initialize("abc123", "test.pdf", 3)
    db.insert_pages(
        [
            PageRecord(page_index=i, classification="scanned", width_pt=612, height_pt=792)
            for i in range(3)
        ]
    )
    yield db
    db.close()


def test_project_info_roundtrip(db):
    info = db.project_info()
    assert info.source_hash == "abc123"
    assert info.source_page_count == 3
    db.check_schema()


def test_page_result_written_atomically_with_flags(db):
    db.write_page_result(
        1, "# Page two", "vlm:glm-ocr-0.9b", "glm-ocr-0.9b", "65a42de",
        [Flag(1, "repetition", 0.8, "loops")],
    )
    page = db.get_page(1)
    assert page.extracted_text == "# Page two"
    assert page.model_revision == "65a42de"
    flags = db.flags_for_page(1)
    assert len(flags) == 1 and flags[0].kind == "repetition"
    # Re-extraction replaces flags rather than accumulating them.
    db.write_page_result(1, "# Better", "vlm:glm-ocr-0.9b", "glm-ocr-0.9b", "65a42de", [])
    assert db.flags_for_page(1) == []


def test_edited_text_precedence_and_preservation(db):
    db.write_page_result(0, "engine output", "tesseract", None, None, [])
    db.set_edited_text(0, "user fixed this")
    assert db.get_page(0).effective_text == "user fixed this"
    # Re-extraction without clear_edited keeps the user's edit.
    db.write_page_result(0, "new engine output", "tesseract", None, None, [])
    assert db.get_page(0).effective_text == "user fixed this"
    # Explicit overwrite clears it.
    db.write_page_result(0, "final", "tesseract", None, None, [], clear_edited=True)
    assert db.get_page(0).effective_text == "final"


def test_completed_pages_survive_reopen(tmp_path):
    path = tmp_path / "crash.ocrproj"
    db = SidecarDB(path)
    db.initialize("h", "x.pdf", 5)
    db.insert_pages(
        [PageRecord(page_index=i, classification="scanned", width_pt=612, height_pt=792)
         for i in range(5)]
    )
    for i in range(3):
        db.write_page_result(i, f"page {i}", "vlm:m", "m", "r", [])
    # Simulate a crash: no clean close of the first connection.
    db2 = SidecarDB(path)
    pages = db2.get_pages()
    assert [p.extracted_text for p in pages[:3]] == ["page 0", "page 1", "page 2"]
    assert pages[3].extracted_text is None
    db2.close()
    db.close()


def test_regions_crud(db):
    rid = db.add_region(
        Region(scope="odd", kind="exclude", order_index=0, x0=0.1, y0=0.0, x1=0.9, y1=0.08)
    )
    regions = db.list_regions()
    assert len(regions) == 1 and regions[0].id == rid and regions[0].scope == "odd"
    r = regions[0]
    r.kind = "column"
    db.update_region(r)
    assert db.list_regions()[0].kind == "column"
    db.delete_region(rid)
    assert db.list_regions() == []


def test_review_status(db):
    db.set_review_status(2, "reviewed")
    assert db.get_page(2).review_status == "reviewed"


def test_missing_page_raises(db):
    with pytest.raises(SidecarError):
        db.get_page(99)
