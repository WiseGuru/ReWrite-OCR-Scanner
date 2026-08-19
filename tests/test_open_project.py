"""Open-project flow: app-data project layout, resume, legacy migration,
moved-PDF recovery, and hash-mismatch detection."""

from __future__ import annotations

import shutil

from rewriteocr.config import projects_dir
from rewriteocr.core.models import FigureRef
from rewriteocr.core.pdf_io import sha256_of_file
from rewriteocr.core.sidecar import SidecarDB, sidecar_path_for
from rewriteocr.jobs.definitions import DiscardSidecarJob, OpenProjectJob
from rewriteocr.pipeline.extract import NullReporter


def test_sidecar_path_is_in_app_data_and_path_keyed(tmp_path):
    a = tmp_path / "one" / "doc.pdf"
    b = tmp_path / "two" / "doc.pdf"
    pa, pb = sidecar_path_for(a), sidecar_path_for(b)
    assert pa.parent == projects_dir()
    assert pa.name.startswith("doc-") and pa.suffix == ".ocrproj"
    assert pa != pb, "same-named PDFs in different folders must not collide"
    assert sidecar_path_for(a) == pa, "keying must be stable"


def test_open_creates_then_resumes(born_digital_pdf):
    first = OpenProjectJob(born_digital_pdf).run(NullReporter())
    assert not first.resumed and not first.hash_mismatch
    assert first.page_count == 6
    assert first.sidecar_path.parent == projects_dir()
    assert not born_digital_pdf.with_suffix(".ocrproj").exists()

    second = OpenProjectJob(born_digital_pdf).run(NullReporter())
    assert second.resumed
    assert second.sidecar_path == first.sidecar_path


def test_moved_pdf_found_by_content_hash(born_digital_pdf, tmp_path):
    first = OpenProjectJob(born_digital_pdf).run(NullReporter())
    moved = tmp_path / "renamed-elsewhere.pdf"
    shutil.move(str(born_digital_pdf), str(moved))
    result = OpenProjectJob(moved).run(NullReporter())
    assert result.resumed
    assert result.sidecar_path == first.sidecar_path


def test_changed_source_reports_hash_mismatch(born_digital_pdf, garbage_text_pdf):
    OpenProjectJob(born_digital_pdf).run(NullReporter())
    # Same path, different content.
    shutil.copy(str(garbage_text_pdf), str(born_digital_pdf))
    result = OpenProjectJob(born_digital_pdf).run(NullReporter())
    assert result.hash_mismatch


def test_legacy_sidecar_migrates_with_figure_refs(born_digital_pdf):
    legacy = born_digital_pdf.with_suffix(".ocrproj")
    old_figs = born_digital_pdf.parent / (legacy.stem + "_figures")
    old_figs.mkdir()
    (old_figs / "page0001_fig01.png").write_bytes(b"png")
    with SidecarDB(legacy) as db:
        db.initialize(sha256_of_file(born_digital_pdf), born_digital_pdf.name, 6)
        from rewriteocr.core.models import PageRecord

        db.insert_pages(
            [PageRecord(page_index=i, classification="born_digital",
                        width_pt=612, height_pt=792) for i in range(6)]
        )
        db.write_page_result(
            0, f"Text\n\n![Figure]({old_figs.name}/page0001_fig01.png)",
            "text_layer", None, None, [],
        )
        db.add_figure(FigureRef(page_index=0,
                                file_path=f"{old_figs.name}/page0001_fig01.png"))

    result = OpenProjectJob(born_digital_pdf).run(NullReporter())
    assert result.resumed
    assert not legacy.exists()
    assert not old_figs.exists()
    new_figs_name = result.sidecar_path.stem + "_figures"
    assert (projects_dir() / new_figs_name / "page0001_fig01.png").is_file()
    with SidecarDB(result.sidecar_path) as db:
        page = db.get_page(0)
        assert f"]({new_figs_name}/page0001_fig01.png)" in page.extracted_text
        assert db.figures_for_page(0)[0].file_path.startswith(new_figs_name + "/")


def test_legacy_migration_move_failure_opens_in_place(born_digital_pdf, monkeypatch):
    """A PDF on another drive makes os.rename impossible; even shutil.move
    can fail (permissions). The open must fall back to using the legacy
    sidecar where it is, never error out."""
    legacy = born_digital_pdf.with_suffix(".ocrproj")
    with SidecarDB(legacy) as db:
        db.initialize(sha256_of_file(born_digital_pdf), born_digital_pdf.name, 6)
        from rewriteocr.core.models import PageRecord

        db.insert_pages(
            [PageRecord(page_index=i, classification="born_digital",
                        width_pt=612, height_pt=792) for i in range(6)]
        )

    def failing_move(src, dst, *args, **kwargs):
        raise OSError(17, "The system cannot move the file to a different disk drive")

    monkeypatch.setattr("rewriteocr.jobs.definitions.shutil.move", failing_move)
    result = OpenProjectJob(born_digital_pdf).run(NullReporter())
    assert result.resumed
    assert result.sidecar_path == legacy
    assert legacy.is_file()


def test_discard_removes_project_and_figures(born_digital_pdf):
    result = OpenProjectJob(born_digital_pdf).run(NullReporter())
    figs = result.sidecar_path.parent / (result.sidecar_path.stem + "_figures")
    figs.mkdir(exist_ok=True)
    (figs / "x.png").write_bytes(b"png")
    DiscardSidecarJob(result.sidecar_path).run(NullReporter())
    assert not result.sidecar_path.exists()
    assert not figs.exists()
