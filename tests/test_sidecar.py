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


def test_document_mode_defaults_to_prose_and_round_trips(db):
    assert db.project_info().document_mode == "prose"
    db.set_document_mode("screenplay")
    assert db.project_info().document_mode == "screenplay"


# Schema 1: the project table before document_mode was added.
_V1_DDL = """
CREATE TABLE project (
  id                INTEGER PRIMARY KEY CHECK (id = 1),
  source_hash       TEXT NOT NULL,
  source_filename   TEXT NOT NULL,
  source_page_count INTEGER NOT NULL,
  app_version       TEXT NOT NULL,
  schema_version    INTEGER NOT NULL,
  created_at        TEXT NOT NULL,
  modified_at       TEXT NOT NULL
);
CREATE TABLE pages (
  page_index     INTEGER PRIMARY KEY,
  classification TEXT NOT NULL,
  deskew_angle   REAL DEFAULT 0.0,
  rotation       INTEGER DEFAULT 0,
  width_pt       REAL NOT NULL,
  height_pt      REAL NOT NULL,
  review_status  TEXT DEFAULT 'unreviewed',
  extracted_text TEXT,
  edited_text    TEXT,
  engine_used    TEXT,
  model_id       TEXT,
  model_revision TEXT,
  extracted_at   TEXT
);
"""


def test_v1_sidecar_migrates_forward_without_loss(tmp_path):
    import sqlite3

    path = tmp_path / "legacy.ocrproj"
    conn = sqlite3.connect(path)
    conn.executescript(_V1_DDL)
    conn.execute(
        "INSERT INTO project VALUES (1, 'h', 'old.pdf', 2, '0.0.1', 1, 't', 't')"
    )
    conn.execute(
        "INSERT INTO pages (page_index, classification, width_pt, height_pt,"
        " extracted_text) VALUES (0, 'scanned', 612, 792, 'kept text')"
    )
    conn.commit()
    conn.close()

    db = SidecarDB(path)
    db.check_schema()
    info = db.project_info()
    assert info.schema_version == 2
    assert info.document_mode == "prose"
    assert info.source_filename == "old.pdf"
    assert db.get_page(0).extracted_text == "kept text"
    # Re-running is a no-op, not a second ALTER.
    db.check_schema()
    assert db.project_info().schema_version == 2
    db.close()


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
