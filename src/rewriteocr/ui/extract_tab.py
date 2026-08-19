"""Extract tab: queue progress, pause/resume/cancel, engine and device
readout, live per-page results in the strip via page_updated."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rewriteocr.jobs.definitions import ExtractJob
from rewriteocr.pipeline.extract import ExtractOptions, ExtractStats
from rewriteocr.ui.dialogs.model_dialog import ModelDownloadDialog
from rewriteocr.ui.state import ProjectContext


def format_eta(seconds: float | None) -> str:
    if seconds is None:
        return "estimating..."
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600}h {seconds % 3600 // 60}m remaining"
    if seconds >= 60:
        return f"{seconds // 60}m {seconds % 60}s remaining"
    return f"{seconds}s remaining"


class ExtractTab(QWidget):
    def __init__(self, context: ProjectContext) -> None:
        super().__init__()
        self.context = context
        self._job: ExtractJob | None = None

        layout = QVBoxLayout(self)
        engine_row = QHBoxLayout()
        engine_row.addWidget(QLabel("Engine:"))
        self.engine_combo = QComboBox()
        engine_row.addWidget(self.engine_combo, 1)
        self.device_label = QLabel("")
        engine_row.addWidget(self.device_label)
        layout.addLayout(engine_row)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("Start extraction")
        self.pause_btn = QPushButton("Pause")
        self.resume_btn = QPushButton("Resume")
        self.cancel_btn = QPushButton("Cancel")
        for b in (self.start_btn, self.pause_btn, self.resume_btn, self.cancel_btn):
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.eta_label = QLabel("")
        layout.addWidget(self.eta_label)

        self.log_list = QListWidget()
        layout.addWidget(self.log_list, 1)

        self.start_btn.clicked.connect(self._start)
        self.pause_btn.clicked.connect(self._pause)
        self.resume_btn.clicked.connect(self._resume)
        self.cancel_btn.clicked.connect(self._cancel)

        jobs = context.jobs
        jobs.job_progress.connect(self._on_progress)
        jobs.job_device_changed.connect(self._on_device)
        jobs.job_message.connect(self._on_message)
        jobs.job_finished.connect(self._on_finished)
        jobs.job_failed.connect(self._on_failed)
        jobs.job_cancelled.connect(self._on_cancelled)
        context.project_opened.connect(self._refresh)
        context.project_closed.connect(self._refresh)
        context.model_status_changed.connect(self._refresh)
        self._refresh()

    # -- engine choice -------------------------------------------------------

    def _refresh(self) -> None:
        self.engine_combo.clear()
        selected = self.context.selected_model()
        if selected:
            spec, quant = selected
            self.engine_combo.addItem(
                f"{spec.display_name} ({quant}), Tesseract cross-check", "auto"
            )
        if self.context.env.has_tesseract:
            self.engine_combo.addItem("Tesseract only (lower fidelity)", "tesseract")
        if self.engine_combo.count() == 0:
            self.engine_combo.addItem("Text layer only (no OCR engine installed)", "auto")
        self._set_running(False)

    def _set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(
            not running and self.context.is_open and not self.context.read_only
        )
        self.pause_btn.setEnabled(running)
        self.resume_btn.setEnabled(False)
        self.cancel_btn.setEnabled(running)
        self.engine_combo.setEnabled(not running)

    # -- actions -------------------------------------------------------------

    def _start(self) -> None:
        if not self.context.is_open or self._job is not None:
            return
        counts = {"scanned": 0, "mixed": 0}
        for p in self.context.db.get_pages():
            if p.extracted_text is None and p.classification in counts:
                counts[p.classification] += 1
        engine = self.engine_combo.currentData() or "auto"
        selected = self.context.selected_model()
        if (
            (counts["scanned"] or counts["mixed"])
            and engine == "auto"
            and selected is None
        ):
            if self.context.env.has_tesseract:
                answer = QMessageBox.question(
                    self, "No model installed",
                    "Scanned pages will be read with Tesseract only, which keeps"
                    " less structure. Download the recommended model instead?",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                )
                if answer == QMessageBox.Cancel:
                    return
                if answer == QMessageBox.Yes:
                    ModelDownloadDialog(self.context, self).exec()
                    selected = self.context.selected_model()
                    if selected is None:
                        return
            else:
                answer = QMessageBox.question(
                    self, "No OCR engine",
                    "This document has scanned pages but no OCR model is"
                    " installed and Tesseract was not found. Download a model now?",
                    QMessageBox.Yes | QMessageBox.Cancel,
                )
                if answer != QMessageBox.Yes:
                    return
                ModelDownloadDialog(self.context, self).exec()
                selected = self.context.selected_model()
                if selected is None:
                    return

        opts = ExtractOptions(engine=engine)
        if selected and engine != "tesseract":
            opts.spec, opts.quant_name = selected
        self._job = ExtractJob(
            self.context.pdf_path, self.context.sidecar_path, opts,
            password=self.context.password,
        )
        self.log_list.clear()
        self.progress.setValue(0)
        self._set_running(True)
        self.context.jobs.submit(self._job)

    def _pause(self) -> None:
        self.context.jobs.pause_current()
        self.pause_btn.setEnabled(False)
        self.resume_btn.setEnabled(True)
        self.eta_label.setText("Paused.")

    def _resume(self) -> None:
        self.context.jobs.resume_current()
        self.pause_btn.setEnabled(True)
        self.resume_btn.setEnabled(False)

    def _cancel(self) -> None:
        self.context.jobs.cancel_current()

    # -- job signals ---------------------------------------------------------

    def _on_progress(self, job, done: int, total: int, eta) -> None:
        if job is not self._job:
            return
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.eta_label.setText(f"{done}/{total} pages. {format_eta(eta)}")

    def _on_device(self, job, device: str) -> None:
        if job is self._job:
            self.context.device = device
            self.context.device_changed.emit(device)
            label = "GPU" if device == "gpu" else "CPU"
            self.device_label.setText(f"Running on {label}")
            if device == "cpu":
                self._log("Running on CPU. This is slower but fully functional.")

    def _on_message(self, job, text: str) -> None:
        if job is self._job:
            self._log(text)

    def _on_finished(self, job, result) -> None:
        if job is not self._job:
            return
        self._job = None
        self._set_running(False)
        if isinstance(result, ExtractStats):
            msg = f"Done: {result.pages_done} pages extracted."
            if result.pages_failed:
                failed = ", ".join(str(i + 1) for i in result.pages_failed[:20])
                msg += f" Failed pages: {failed}."
            if result.device_fallback:
                msg += " Part of the run fell back to CPU."
            self._log(msg)
            self.eta_label.setText(msg)

    def _on_failed(self, job, detail: str) -> None:
        if job is not self._job:
            return
        self._job = None
        self._set_running(False)
        self._log("Extraction failed: " + detail.splitlines()[0])
        QMessageBox.critical(self, "Extraction failed", detail.splitlines()[0])

    def _on_cancelled(self, job) -> None:
        if job is not self._job:
            return
        self._job = None
        self._set_running(False)
        self._log("Cancelled. Completed pages are saved.")
        self.eta_label.setText("Cancelled. Completed pages are saved.")

    def _log(self, text: str) -> None:
        self.log_list.addItem(text)
        self.log_list.scrollToBottom()
