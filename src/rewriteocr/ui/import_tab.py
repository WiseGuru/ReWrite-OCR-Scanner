"""Import tab: file picker, triage summary, model status, resume offer."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rewriteocr.core.pdf_io import PdfDocument, PdfError, PdfPasswordError
from rewriteocr.jobs.definitions import DiscardSidecarJob, OpenProjectJob, OpenResult
from rewriteocr.ui.dialogs.model_dialog import ModelDownloadDialog
from rewriteocr.ui.state import ProjectContext

log = logging.getLogger("rewriteocr.ui.import")


class ImportTab(QWidget):
    def __init__(self, context: ProjectContext) -> None:
        super().__init__()
        self.context = context
        self._open_job: OpenProjectJob | None = None
        self._pending_password: str | None = None

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.open_btn = QPushButton("Open PDF...")
        self.open_btn.clicked.connect(self._pick_file)
        row.addWidget(self.open_btn)
        self.file_label = QLabel("No document open.")
        row.addWidget(self.file_label, 1)
        layout.addLayout(row)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        model_row = QHBoxLayout()
        self.model_label = QLabel("")
        model_row.addWidget(self.model_label, 1)
        self.model_btn = QPushButton("Manage models...")
        self.model_btn.clicked.connect(self._open_model_dialog)
        model_row.addWidget(self.model_btn)
        layout.addLayout(model_row)
        layout.addStretch(1)

        context.jobs.job_finished.connect(self._on_job_finished)
        context.jobs.job_failed.connect(self._on_job_failed)
        context.jobs.job_message.connect(self._on_job_message)
        context.jobs.job_progress.connect(self._on_job_progress)
        context.model_status_changed.connect(self._refresh_model_status)
        self._refresh_model_status()

    # -- opening -------------------------------------------------------------

    def _pick_file(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", self.context.settings.get("last_dir", ""), "PDF files (*.pdf)"
        )
        if not path_str:
            return
        path = Path(path_str)
        self.context.settings.set("last_dir", str(path.parent))
        password: str | None = None
        # Probe for encryption interactively before handing off to the worker.
        while True:
            try:
                PdfDocument(path, password=password).close()
                break
            except PdfPasswordError:
                text, ok = QInputDialog.getText(
                    self, "Password required",
                    "This PDF is password protected. Enter the password:",
                    QLineEdit.Password,
                )
                if not ok:
                    return
                password = text
            except PdfError as exc:
                QMessageBox.critical(
                    self, "Cannot open PDF",
                    f"This file could not be opened:\n{exc}\n\n"
                    "If the file is encrypted with an unsupported method, decrypt"
                    " it with another tool first.",
                )
                return
        self._start_open(path, password)

    def _start_open(self, path: Path, password: str | None) -> None:
        self.context.close_project()
        self._pending_password = password
        self.file_label.setText(str(path))
        self.status_label.setText("Opening...")
        self._open_job = OpenProjectJob(path, password)
        self.context.jobs.submit(self._open_job)

    def _on_job_finished(self, job, result) -> None:
        if job is not self._open_job:
            return
        self._open_job = None
        assert isinstance(result, OpenResult)
        if result.hash_mismatch:
            self._handle_hash_mismatch(job.pdf_path, result)
            return
        self.context.attach_project(
            job.pdf_path, result.sidecar_path, self._pending_password
        )
        self._show_summary(result)

    def _handle_hash_mismatch(self, pdf_path: Path, result: OpenResult) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Source file changed")
        box.setText(
            "This PDF has changed since the project was created. The saved"
            " progress belongs to a different version of the file."
        )
        ro = box.addButton("Open read-only", QMessageBox.AcceptRole)
        discard = box.addButton("Discard saved progress", QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is ro:
            self.context.attach_project(
                pdf_path, result.sidecar_path, self._pending_password, read_only=True
            )
            self.status_label.setText(
                "Read-only: the source changed, so nothing will be written."
            )
        elif clicked is discard:
            self.context.jobs.submit(DiscardSidecarJob(result.sidecar_path))
            self._start_open(pdf_path, self._pending_password)

    def _show_summary(self, result: OpenResult) -> None:
        c = result.counts
        parts = []
        if c.get("born_digital"):
            parts.append(f"{c['born_digital']} with a usable text layer")
        if c.get("scanned"):
            parts.append(f"{c['scanned']} scanned")
        if c.get("mixed"):
            parts.append(f"{c['mixed']} mixed")
        summary = f"{result.page_count} pages: " + ", ".join(parts) if parts else ""
        if result.resumed:
            summary += (
                f". Resumed existing project ({c.get('extracted', 0)} pages"
                " already extracted)."
            )
        self.summary_label.setText(summary)
        self.status_label.setText("Ready. Continue to Rules or Extract.")
        if c.get("scanned") or c.get("mixed"):
            if self.context.selected_model() is None:
                self.status_label.setText(
                    "This document has scanned pages. Download an OCR model, or"
                    " extraction will use Tesseract only."
                )

    def _on_job_failed(self, job, detail: str) -> None:
        if job is self._open_job:
            self._open_job = None
            self.status_label.setText("Open failed.")
            QMessageBox.critical(self, "Open failed", detail.splitlines()[0])

    def _on_job_message(self, job, text: str) -> None:
        if isinstance(job, OpenProjectJob):
            self.status_label.setText(text)

    def _on_job_progress(self, job, done: int, total: int, _eta) -> None:
        if isinstance(job, OpenProjectJob):
            self.status_label.setText(f"Classifying pages ({done}/{total})...")

    # -- model status --------------------------------------------------------

    def _open_model_dialog(self) -> None:
        ModelDownloadDialog(self.context, self).exec()
        self._refresh_model_status()

    def _refresh_model_status(self) -> None:
        selected = self.context.selected_model()
        if selected:
            spec, quant = selected
            self.model_label.setText(f"OCR model ready: {spec.display_name} ({quant})")
        else:
            tess = "Tesseract available" if self.context.env.has_tesseract else (
                "no Tesseract either, so scanned pages cannot be read yet"
            )
            self.model_label.setText(f"No OCR model installed ({tess}).")
