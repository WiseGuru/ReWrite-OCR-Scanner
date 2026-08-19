"""End-to-end pipeline tests without any model: triage, born-digital
extraction with exclusion regions, incremental persistence, cancellation."""

from __future__ import annotations

import threading

import pytest

from rewriteocr.core.models import ExportOptions, Region
from rewriteocr.core.pdf_io import sha256_of_file
from rewriteocr.core.sidecar import SidecarDB
from rewriteocr.jobs.control import JobCancelled, JobControl
from rewriteocr.pipeline.export_md import export_markdown
from rewriteocr.pipeline.extract import (
    ExtractOptions,
    NullReporter,
    extract_document,
    run_triage,
)


@pytest.fixture
def project(born_digital_pdf, tmp_path):
    sidecar = SidecarDB(tmp_path / "born.ocrproj")
    sidecar.initialize(sha256_of_file(born_digital_pdf), "born.pdf", 6)
    run_triage(born_digital_pdf, sidecar, JobControl(), NullReporter())
    yield born_digital_pdf, sidecar
    sidecar.close()


def test_triage_populates_pages(project):
    _, sidecar = project
    pages = sidecar.get_pages()
    assert len(pages) == 6
    assert all(p.classification == "born_digital" for p in pages)


def test_born_digital_extraction_no_model(project):
    pdf, sidecar = project
    stats = extract_document(
        pdf, sidecar, ExtractOptions(), JobControl(), NullReporter()
    )
    assert stats.pages_done == 6
    assert stats.pages_failed == []
    page = sidecar.get_page(0)
    assert page.engine_used == "text_layer"
    assert "body text of page 1" in page.extracted_text


def test_exclusion_region_removes_running_header(project):
    pdf, sidecar = project
    # Header band across the top 8 percent of every page.
    sidecar.add_region(
        Region(scope="all", kind="exclude", order_index=0, x0=0.0, y0=0.0, x1=1.0, y1=0.08)
    )
    extract_document(pdf, sidecar, ExtractOptions(), JobControl(), NullReporter())
    for page in sidecar.get_pages():
        assert "History of Fixtures" not in (page.extracted_text or "")
        assert "body text" in page.extracted_text


def test_extraction_skips_already_extracted(project):
    pdf, sidecar = project
    extract_document(pdf, sidecar, ExtractOptions(), JobControl(), NullReporter())
    stats = extract_document(pdf, sidecar, ExtractOptions(), JobControl(), NullReporter())
    assert stats.pages_done == 0


def test_cancel_preserves_completed_pages(project):
    pdf, sidecar = project
    control = JobControl()
    done_pages: list[int] = []

    class CancellingReporter(NullReporter):
        def page_done(self, page_index: int) -> None:
            done_pages.append(page_index)
            if len(done_pages) == 2:
                control.cancel()

    with pytest.raises(JobCancelled):
        extract_document(pdf, sidecar, ExtractOptions(), control, CancellingReporter())
    pages = sidecar.get_pages()
    assert pages[0].extracted_text is not None
    assert pages[1].extracted_text is not None
    assert pages[5].extracted_text is None


def test_pause_blocks_and_resume_continues(project):
    pdf, sidecar = project
    control = JobControl()
    control.pause()
    started = threading.Event()

    result = {}

    def run():
        started.set()
        # One SidecarDB per thread: the worker opens its own connection.
        with SidecarDB(sidecar.path) as worker_db:
            result["stats"] = extract_document(
                pdf, worker_db, ExtractOptions(), control, NullReporter()
            )

    t = threading.Thread(target=run, daemon=True)
    t.start()
    started.wait(timeout=5)
    t.join(timeout=0.8)
    assert t.is_alive(), "extraction should be blocked while paused"
    control.resume()
    t.join(timeout=30)
    assert not t.is_alive()
    assert result["stats"].pages_done == 6


def test_full_export_roundtrip(project, tmp_path):
    pdf, sidecar = project
    extract_document(pdf, sidecar, ExtractOptions(), JobControl(), NullReporter())
    out = tmp_path / "book.md"
    export_markdown(sidecar, out, ExportOptions(stitch=True))
    text = out.read_text(encoding="utf-8")
    # Stitching rejoins the hyphenated word crossing pages 1-2.
    assert "hyphenated" in text
    # Running headers and page numbers dropped by the 60 percent rule.
    assert "A History of Fixtures" not in text
    assert "Chapter 3" in text


def test_mixed_page_recorded_but_treated_as_scanned(mixed_pdf, tmp_path):
    sidecar = SidecarDB(tmp_path / "m.ocrproj")
    sidecar.initialize(sha256_of_file(mixed_pdf), "m.pdf", 1)
    run_triage(mixed_pdf, sidecar, JobControl(), NullReporter())
    assert sidecar.get_page(0).classification == "mixed"
    sidecar.close()
