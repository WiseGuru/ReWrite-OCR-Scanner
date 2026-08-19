"""Concrete jobs. Each opens its own SidecarDB inside run() because SQLite
connections must stay on the thread that created them. Jobs hold no Qt."""

from __future__ import annotations

import itertools
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from rewriteocr.config import projects_dir
from rewriteocr.constants import SIDECAR_SUFFIX
from rewriteocr.core.models import ExportOptions
from rewriteocr.core.pdf_io import sha256_of_file
from rewriteocr.core.sidecar import SidecarDB, sidecar_path_for
from rewriteocr.jobs.control import JobControl
from rewriteocr.modelmgr import store
from rewriteocr.modelmgr.downloader import download_file
from rewriteocr.modelmgr.manifest import ModelSpec
from rewriteocr.pipeline.export_docx import export_docx
from rewriteocr.pipeline.export_md import export_markdown
from rewriteocr.pipeline.extract import (
    ExtractOptions,
    ExtractStats,
    extract_document,
    run_triage,
)

log = logging.getLogger("rewriteocr.jobs")

_job_counter = itertools.count(1)


class Job:
    description = "job"

    def __init__(self) -> None:
        self.id = next(_job_counter)
        self.control = JobControl()

    def run(self, reporter) -> object:  # pragma: no cover - abstract
        raise NotImplementedError


@dataclass
class OpenResult:
    sidecar_path: Path
    resumed: bool
    hash_mismatch: bool
    page_count: int
    counts: dict[str, int] = field(default_factory=dict)


class OpenProjectJob(Job):
    """Hash the PDF, find or create the sidecar, triage when new.

    Lookup order: the path-keyed sidecar in the projects dir, then a legacy
    sidecar next to the PDF (migrated in), then a content-hash scan of the
    projects dir (catches a moved or renamed PDF)."""

    description = "Opening document"

    def __init__(self, pdf_path: Path, password: str | None = None) -> None:
        super().__init__()
        self.pdf_path = Path(pdf_path)
        self.password = password

    def run(self, reporter) -> OpenResult:
        reporter.message("Hashing source file...")
        source_hash = sha256_of_file(self.pdf_path)
        sc_path = sidecar_path_for(self.pdf_path)

        if not sc_path.is_file():
            in_place = self._migrate_legacy_sidecar(sc_path, source_hash, reporter)
            if in_place is not None:
                # Migration could not move the files; keep using the legacy
                # sidecar where it is rather than failing the open.
                with SidecarDB(in_place) as db:
                    info = db.project_info()
                    db.check_schema()
                    return self._resumed(in_place, db, info)

        if sc_path.is_file():
            with SidecarDB(sc_path) as db:
                info = db.project_info()
                db.check_schema()
                if info.source_hash == source_hash:
                    return self._resumed(sc_path, db, info)
            return OpenResult(
                sidecar_path=sc_path,
                resumed=False,
                hash_mismatch=True,
                page_count=0,
            )

        found = self._scan_by_content_hash(source_hash)
        if found is not None:
            with SidecarDB(found) as db:
                info = db.project_info()
                db.check_schema()
                reporter.message("Found existing progress for this file's content.")
                return self._resumed(found, db, info)

        reporter.message("Classifying pages...")
        with SidecarDB(sc_path) as db:
            db.initialize(source_hash, self.pdf_path.name, 0)
            records = run_triage(
                self.pdf_path, db, self.control, reporter, password=self.password
            )
            db.set_page_count(len(records))
            counts = self._counts(db)
            return OpenResult(
                sidecar_path=sc_path,
                resumed=False,
                hash_mismatch=False,
                page_count=len(records),
                counts=counts,
            )

    def _resumed(self, path: Path, db: SidecarDB, info) -> OpenResult:
        return OpenResult(
            sidecar_path=path,
            resumed=True,
            hash_mismatch=False,
            page_count=info.source_page_count,
            counts=self._counts(db),
        )

    def _migrate_legacy_sidecar(
        self, sc_path: Path, source_hash: str, reporter
    ) -> Path | None:
        """Early builds wrote the sidecar and figures next to the PDF. Move a
        matching one into the projects dir and rewrite figure references to
        the new figures dir name. shutil.move throughout: os.rename cannot
        cross drive boundaries and PDFs often live on another volume.

        Returns None normally; returns the legacy path when the files could
        not be moved, so the caller opens the project in place instead of
        failing."""
        legacy = self.pdf_path.with_suffix(sc_path.suffix)
        if not legacy.is_file():
            return None
        try:
            with SidecarDB(legacy) as db:
                if db.project_info().source_hash != source_hash:
                    return None
        except Exception:
            return None
        reporter.message("Moving project data into the app data folder...")
        try:
            shutil.move(str(legacy), str(sc_path))
            for suffix in ("-wal", "-shm"):
                extra = Path(str(legacy) + suffix)
                if extra.is_file():
                    shutil.move(str(extra), str(sc_path) + suffix)
        except OSError as exc:
            log.warning("Legacy project migration failed (%s); opening in place", exc)
            reporter.message(
                "Could not move the old project data; continuing with it in place."
            )
            return legacy if legacy.is_file() else None
        old_figs_name = legacy.stem + "_figures"
        new_figs_name = sc_path.stem + "_figures"
        old_figs = legacy.parent / old_figs_name
        try:
            if old_figs.is_dir():
                shutil.move(str(old_figs), str(sc_path.parent / new_figs_name))
        except OSError as exc:
            log.warning("Figures folder migration failed: %s", exc)
        with SidecarDB(sc_path) as db:
            db.rewrite_figure_prefix(old_figs_name, new_figs_name)
        return None

    @staticmethod
    def _scan_by_content_hash(source_hash: str) -> Path | None:
        for candidate in sorted(projects_dir().glob(f"*{SIDECAR_SUFFIX}")):
            try:
                with SidecarDB(candidate) as db:
                    if db.project_info().source_hash == source_hash:
                        return candidate
            except Exception:
                continue
        return None

    @staticmethod
    def _counts(db: SidecarDB) -> dict[str, int]:
        counts: dict[str, int] = {"born_digital": 0, "scanned": 0, "mixed": 0, "extracted": 0}
        for p in db.get_pages():
            counts[p.classification] = counts.get(p.classification, 0) + 1
            if p.extracted_text is not None:
                counts["extracted"] += 1
        return counts


class DiscardSidecarJob(Job):
    """Delete a stale sidecar (hash mismatch) then reopen fresh."""

    description = "Discarding old project data"

    def __init__(self, sidecar_path: Path) -> None:
        super().__init__()
        self.sidecar_path = Path(sidecar_path)

    def run(self, reporter) -> None:
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(self.sidecar_path) + suffix)
            p.unlink(missing_ok=True)
        figures = self.sidecar_path.parent / (self.sidecar_path.stem + "_figures")
        if figures.is_dir():
            shutil.rmtree(figures, ignore_errors=True)


class ExtractJob(Job):
    description = "Extracting"

    def __init__(
        self,
        pdf_path: Path,
        sidecar_path: Path,
        opts: ExtractOptions,
        password: str | None = None,
    ) -> None:
        super().__init__()
        self.pdf_path = Path(pdf_path)
        self.sidecar_path = Path(sidecar_path)
        self.opts = opts
        self.password = password

    def run(self, reporter) -> ExtractStats:
        with SidecarDB(self.sidecar_path) as db:
            return extract_document(
                self.pdf_path, db, self.opts, self.control, reporter,
                password=self.password,
            )


class ExportJob(Job):
    description = "Exporting"

    def __init__(self, sidecar_path: Path, out_path: Path, options: ExportOptions) -> None:
        super().__init__()
        self.sidecar_path = Path(sidecar_path)
        self.out_path = Path(out_path)
        self.options = options

    def run(self, reporter):
        with SidecarDB(self.sidecar_path) as db:
            if self.options.fmt == "docx":
                log = export_docx(db, self.out_path, self.options)
            else:
                log = export_markdown(db, self.out_path, self.options)
        return self.out_path, log


class DownloadModelJob(Job):
    description = "Downloading model"

    def __init__(self, spec: ModelSpec, quant_name: str) -> None:
        super().__init__()
        self.spec = spec
        self.quant_name = quant_name

    def run(self, reporter):
        quant = self.spec.quant(self.quant_name)
        total_bytes = (quant.size_mb + self.spec.mmproj.size_mb) * 1024 * 1024
        done_offset = 0

        def progress_for(base: int):
            def cb(done: int, _total) -> None:
                reporter.progress(base + done, total_bytes, None)
            return cb

        reporter.message(f"Downloading {quant.file}...")
        dest = store.quant_path(self.spec, quant)
        download_file(
            self.spec.file_url(quant.file), dest, quant.sha256,
            expected_size=quant.size_mb * 1024 * 1024,
            progress=progress_for(done_offset),
            checkpoint=self.control.checkpoint,
        )
        done_offset = quant.size_mb * 1024 * 1024
        reporter.message(f"Downloading {self.spec.mmproj.file}...")
        download_file(
            self.spec.file_url(self.spec.mmproj.file),
            store.mmproj_path(self.spec),
            self.spec.mmproj.sha256,
            expected_size=self.spec.mmproj.size_mb * 1024 * 1024,
            progress=progress_for(done_offset),
            checkpoint=self.control.checkpoint,
        )
        reporter.message("Download complete.")
        return dest
