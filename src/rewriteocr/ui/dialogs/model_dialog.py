"""Model download dialog: quant choice with plain-language tradeoffs, disk
precheck figures, license acknowledgment before first use, resumable
download with progress."""

from __future__ import annotations

import shutil

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from rewriteocr.config import models_dir
from rewriteocr.jobs.definitions import DownloadModelJob
from rewriteocr.modelmgr import licenses, store
from rewriteocr.modelmgr.manifest import ModelSpec
from rewriteocr.ui.state import ProjectContext


class ModelDownloadDialog(QDialog):
    def __init__(self, context: ProjectContext, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self.setWindowTitle("Download OCR model")
        self.setMinimumWidth(520)
        self._job: DownloadModelJob | None = None

        layout = QVBoxLayout(self)

        self.model_combo = QComboBox()
        for spec in context.manifest:
            self.model_combo.addItem(spec.display_name, spec.id)
        layout.addWidget(QLabel("Model:"))
        layout.addWidget(self.model_combo)
        self.model_desc = QLabel()
        self.model_desc.setWordWrap(True)
        layout.addWidget(self.model_desc)

        layout.addWidget(QLabel("Quality / size:"))
        self._quant_buttons: list[QRadioButton] = []
        self._quant_box = QVBoxLayout()
        layout.addLayout(self._quant_box)

        self.disk_label = QLabel()
        layout.addWidget(self.disk_label)

        self.license_label = QLabel()
        self.license_label.setWordWrap(True)
        self.license_label.setOpenExternalLinks(True)
        layout.addWidget(self.license_label)
        self.ack_check = QCheckBox("I have read and accept the model license")
        layout.addWidget(self.ack_check)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        self.download_btn = QPushButton("Download")
        self.cancel_btn = QPushButton("Close")
        buttons.addStretch(1)
        buttons.addWidget(self.download_btn)
        buttons.addWidget(self.cancel_btn)
        layout.addLayout(buttons)

        self.model_combo.currentIndexChanged.connect(self._refresh)
        self.download_btn.clicked.connect(self._start_download)
        self.cancel_btn.clicked.connect(self._on_close)
        self.ack_check.toggled.connect(self._update_enabled)

        context.jobs.job_progress.connect(self._on_progress)
        context.jobs.job_message.connect(self._on_message)
        context.jobs.job_finished.connect(self._on_finished)
        context.jobs.job_failed.connect(self._on_failed)
        context.jobs.job_cancelled.connect(self._on_cancelled)

        self._refresh()

    # -- state ---------------------------------------------------------------

    def _spec(self) -> ModelSpec:
        model_id = self.model_combo.currentData()
        return next(m for m in self.context.manifest if m.id == model_id)

    def _quant_name(self) -> str:
        for btn in self._quant_buttons:
            if btn.isChecked():
                return btn.property("quant_name")
        return self._spec().quants[0].name

    def _refresh(self) -> None:
        spec = self._spec()
        self.model_desc.setText(f"{spec.description} License: {spec.license}.")
        while self._quant_box.count():
            w = self._quant_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._quant_buttons.clear()
        for i, quant in enumerate(spec.quants):
            installed = store.is_quant_installed(spec, quant)
            suffix = " (installed)" if installed else ""
            btn = QRadioButton(
                f"{quant.name}: {quant.label}. {quant.size_mb} MB download,"
                f" about {quant.ram_mb} MB memory while running.{suffix}"
            )
            btn.setProperty("quant_name", quant.name)
            btn.setChecked(i == 0)
            btn.toggled.connect(self._update_enabled)
            self._quant_buttons.append(btn)
            self._quant_box.addWidget(btn)

        free_gb = shutil.disk_usage(models_dir()).free / 1e9
        total_mb = spec.quants[0].size_mb + spec.mmproj.size_mb
        self.disk_label.setText(
            f"Includes a {spec.mmproj.size_mb} MB vision component."
            f" Free disk space: {free_gb:.1f} GB."
        )
        self.license_label.setText(
            f'License: <a href="{spec.license_url}">{spec.license} ({spec.license_url})</a>'
        )
        already = licenses.is_acknowledged(spec.id)
        self.ack_check.setVisible(not already)
        self.ack_check.setChecked(already)
        del total_mb
        self._update_enabled()

    def _update_enabled(self) -> None:
        spec = self._spec()
        quant = spec.quant(self._quant_name())
        installed = store.is_quant_installed(spec, quant)
        acked = self.ack_check.isChecked() or licenses.is_acknowledged(spec.id)
        self.download_btn.setEnabled(acked and not installed and self._job is None)
        if installed:
            self.status_label.setText("This quant is already installed.")

    # -- download ------------------------------------------------------------

    def _start_download(self) -> None:
        spec = self._spec()
        if not licenses.is_acknowledged(spec.id):
            licenses.record_acknowledgment(spec.id, spec.license)
        self._job = DownloadModelJob(spec, self._quant_name())
        self.progress.setVisible(True)
        self.progress.setRange(0, 1000)
        self.download_btn.setEnabled(False)
        self.model_combo.setEnabled(False)
        self.cancel_btn.setText("Cancel download")
        self.context.jobs.submit(self._job)

    def _on_progress(self, job, done: int, total: int, _eta) -> None:
        if job is self._job and total:
            self.progress.setValue(int(done / total * 1000))

    def _on_message(self, job, text: str) -> None:
        if job is self._job:
            self.status_label.setText(text)

    def _on_finished(self, job, _result) -> None:
        if job is not self._job:
            return
        spec = self._spec()
        self.context.set_selected_model(spec.id, self._quant_name())
        self._job = None
        self.status_label.setText("Model installed and selected.")
        self.progress.setVisible(False)
        self.cancel_btn.setText("Close")
        self.model_combo.setEnabled(True)
        self._refresh()

    def _on_failed(self, job, detail: str) -> None:
        if job is not self._job:
            return
        self._job = None
        self.progress.setVisible(False)
        self.cancel_btn.setText("Close")
        self.model_combo.setEnabled(True)
        QMessageBox.warning(self, "Download failed", detail.splitlines()[0])
        self._update_enabled()

    def _on_cancelled(self, job) -> None:
        if job is not self._job:
            return
        self._job = None
        self.progress.setVisible(False)
        self.cancel_btn.setText("Close")
        self.model_combo.setEnabled(True)
        self.status_label.setText("Download cancelled. It will resume where it left off.")
        self._update_enabled()

    def _on_close(self) -> None:
        if self._job is not None:
            self._job.control.cancel()
        else:
            self.accept()

    def closeEvent(self, event) -> None:
        if self._job is not None:
            self._job.control.cancel()
        super().closeEvent(event)
