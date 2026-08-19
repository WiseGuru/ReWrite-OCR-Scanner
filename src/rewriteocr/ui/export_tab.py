"""Export tab: format, options, output path, and a confirmation summarizing
unreviewed flagged pages before writing."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from rewriteocr.core.models import ExportOptions, StitchLog
from rewriteocr.jobs.definitions import ExportJob
from rewriteocr.ui.state import ProjectContext


class ExportTab(QWidget):
    def __init__(self, context: ProjectContext) -> None:
        super().__init__()
        self.context = context
        self._job: ExportJob | None = None

        layout = QVBoxLayout(self)
        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("Format:"))
        self.md_radio = QRadioButton("Markdown (.md)")
        self.md_radio.setChecked(True)
        self.docx_radio = QRadioButton("Word (.docx)")
        fmt_row.addWidget(self.md_radio)
        fmt_row.addWidget(self.docx_radio)
        fmt_row.addStretch(1)
        layout.addLayout(fmt_row)

        opt_row = QHBoxLayout()
        opt_row.addWidget(QLabel("Page breaks:"))
        self.break_combo = QComboBox()
        self.break_combo.addItem("None", "none")
        self.break_combo.addItem("HTML comment", "comment")
        self.break_combo.addItem("Horizontal rule / page break", "rule")
        opt_row.addWidget(self.break_combo)
        self.stitch_check = QCheckBox(
            "Cross-page cleanup (rejoin hyphenated words, drop running headers,"
            " merge continued tables)"
        )
        self.stitch_check.setChecked(True)
        opt_row.addWidget(self.stitch_check)
        opt_row.addStretch(1)
        layout.addLayout(opt_row)

        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Output file:"))
        self.path_edit = QLineEdit()
        path_row.addWidget(self.path_edit, 1)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse)
        path_row.addWidget(browse_btn)
        layout.addLayout(path_row)

        self.warn_label = QLabel("")
        self.warn_label.setWordWrap(True)
        layout.addWidget(self.warn_label)

        self.export_btn = QPushButton("Export")
        self.export_btn.clicked.connect(self._export)
        layout.addWidget(self.export_btn)
        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)
        layout.addStretch(1)

        self.md_radio.toggled.connect(self._sync_extension)
        context.project_opened.connect(self._on_project_opened)
        context.jobs.job_finished.connect(self._on_finished)
        context.jobs.job_failed.connect(self._on_failed)

    def _on_project_opened(self) -> None:
        if self.context.pdf_path is not None:
            default = self.context.pdf_path.with_suffix(".md")
            self.path_edit.setText(str(default))

    def _sync_extension(self) -> None:
        text = self.path_edit.text().strip()
        if not text:
            return
        suffix = ".md" if self.md_radio.isChecked() else ".docx"
        self.path_edit.setText(str(Path(text).with_suffix(suffix)))

    def _browse(self) -> None:
        if self.md_radio.isChecked():
            filt, suffix = "Markdown (*.md)", ".md"
        else:
            filt, suffix = "Word document (*.docx)", ".docx"
        start = self.path_edit.text() or self.context.settings.get("last_dir", "")
        path, _ = QFileDialog.getSaveFileName(self, "Export to", start, filt)
        if path:
            if not path.lower().endswith(suffix):
                path += suffix
            self.path_edit.setText(path)

    def _unreviewed_flagged(self) -> list[int]:
        if not self.context.is_open:
            return []
        flagged = {f.page_index for f in self.context.db.all_flags()}
        return sorted(
            i for i in flagged
            if self.context.db.get_page(i).review_status == "unreviewed"
        )

    def _export(self) -> None:
        if not self.context.is_open or self._job is not None:
            return
        out_text = self.path_edit.text().strip()
        if not out_text:
            QMessageBox.information(self, "Choose a file", "Pick an output file first.")
            return
        pending = self._unreviewed_flagged()
        if pending:
            listed = ", ".join(str(i + 1) for i in pending[:15])
            more = "..." if len(pending) > 15 else ""
            answer = QMessageBox.question(
                self, "Unreviewed flagged pages",
                f"{len(pending)} flagged page(s) have not been reviewed"
                f" (pages {listed}{more}). Export anyway?",
                QMessageBox.Yes | QMessageBox.Cancel,
            )
            if answer != QMessageBox.Yes:
                return
        options = ExportOptions(
            fmt="docx" if self.docx_radio.isChecked() else "markdown",
            page_break=self.break_combo.currentData(),
            stitch=self.stitch_check.isChecked(),
        )
        self._job = ExportJob(self.context.sidecar_path, Path(out_text), options)
        self.export_btn.setEnabled(False)
        self.result_label.setText("Exporting...")
        self.context.jobs.submit(self._job)

    def _on_finished(self, job, result) -> None:
        if job is not self._job:
            return
        self._job = None
        self.export_btn.setEnabled(True)
        out_path, log = result
        assert isinstance(log, StitchLog)
        notes = []
        if log.hyphen_joins:
            notes.append(f"{len(log.hyphen_joins)} hyphenated word(s) rejoined")
        if log.headers_dropped:
            notes.append(f"{len(log.headers_dropped)} running header/footer pattern(s) removed")
        if log.tables_merged:
            notes.append(f"{len(log.tables_merged)} table(s) merged across pages")
        note = ("; ".join(notes) + ".") if notes else ""
        self.result_label.setText(f"Exported to {out_path}. {note}")

    def _on_failed(self, job, detail: str) -> None:
        if job is not self._job:
            return
        self._job = None
        self.export_btn.setEnabled(True)
        self.result_label.setText("Export failed.")
        QMessageBox.critical(self, "Export failed", detail.splitlines()[0])
