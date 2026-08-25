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
    QVBoxLayout,
    QWidget,
)

from rewriteocr.core.models import ExportOptions, StitchLog
from rewriteocr.jobs.definitions import ExportJob
from rewriteocr.pipeline.formats import format_spec, formats_for_mode
from rewriteocr.ui.state import ProjectContext


class ExportTab(QWidget):
    def __init__(self, context: ProjectContext) -> None:
        super().__init__()
        self.context = context
        self._job: ExportJob | None = None

        layout = QVBoxLayout(self)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Document is:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Prose", "prose")
        self.mode_combo.addItem("Screenplay or stage play", "screenplay")
        mode_row.addWidget(self.mode_combo)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("Format:"))
        self.fmt_combo = QComboBox()
        fmt_row.addWidget(self.fmt_combo)
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

        self.format_hint = QLabel("")
        self.format_hint.setWordWrap(True)
        layout.addWidget(self.format_hint)

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

        self._populate_formats("prose")
        self.fmt_combo.currentIndexChanged.connect(self._on_format_changed)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        context.project_opened.connect(self._on_project_opened)
        context.jobs.job_finished.connect(self._on_finished)
        context.jobs.job_failed.connect(self._on_failed)

    # -- format and mode -----------------------------------------------------

    def _populate_formats(self, mode: str) -> None:
        """Rebuild the format list for the document mode, keeping the current
        selection when that format is still on offer."""
        previous = self.fmt_combo.currentData()
        self.fmt_combo.blockSignals(True)
        self.fmt_combo.clear()
        for spec in formats_for_mode(mode):
            self.fmt_combo.addItem(spec.label, spec.key)
        index = self.fmt_combo.findData(previous)
        self.fmt_combo.setCurrentIndex(max(index, 0))
        self.fmt_combo.blockSignals(False)
        self._apply_format()

    def _spec(self):
        return format_spec(self.fmt_combo.currentData() or "markdown")

    def _apply_format(self) -> None:
        spec = self._spec()
        # Screenplay formats paginate themselves: Final Draft and Word both
        # repaginate on open, so forcing OCR page boundaries only makes short
        # pages.
        self.break_combo.setEnabled(not spec.screenplay)
        if spec.screenplay:
            self.format_hint.setText(
                "Screenplay formats paginate themselves, so the page-break"
                " option does not apply. Blocks are classified as scene"
                " heading, action, character, parenthetical, dialogue or"
                " transition before writing."
            )
        else:
            self.format_hint.setText("")

    def _on_format_changed(self) -> None:
        self._apply_format()
        self._sync_extension()

    def _on_mode_changed(self) -> None:
        mode = self.mode_combo.currentData()
        if self.context.is_open and not self.context.read_only:
            self.context.db.set_document_mode(mode)
        self._populate_formats(mode)
        self._sync_extension()

    def _on_project_opened(self) -> None:
        mode = "prose"
        if self.context.is_open:
            mode = self.context.db.project_info().document_mode
        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentIndex(max(self.mode_combo.findData(mode), 0))
        self.mode_combo.blockSignals(False)
        self._populate_formats(mode)
        if self.context.pdf_path is not None:
            default = self.context.pdf_path.with_suffix(self._spec().suffix)
            self.path_edit.setText(str(default))

    def _sync_extension(self) -> None:
        text = self.path_edit.text().strip()
        if not text:
            return
        self.path_edit.setText(str(Path(text).with_suffix(self._spec().suffix)))

    def _browse(self) -> None:
        spec = self._spec()
        start = self.path_edit.text() or self.context.settings.get("last_dir", "")
        path, _ = QFileDialog.getSaveFileName(self, "Export to", start, spec.file_filter)
        if path:
            if not path.lower().endswith(spec.suffix):
                path += spec.suffix
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
            fmt=self.fmt_combo.currentData(),
            page_break=self.break_combo.currentData(),
            stitch=self.stitch_check.isChecked(),
        )
        self._job = ExportJob(
            self.context.sidecar_path,
            Path(out_text),
            options,
            pdf_path=self.context.pdf_path,
        )
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
        if log.screenplay is not None:
            report = log.screenplay
            kind = "stage play" if report.stage_play else "screenplay"
            notes.append(f"{sum(report.counts.values())} {kind} elements classified")
            if report.stage_play:
                notes.append(f"{len(report.cast)} speaking characters found")
            if report.geometry_pages:
                notes.append(f"column positions used on {report.geometry_pages} page(s)")
            if report.low_confidence:
                notes.append(f"{len(report.low_confidence)} uncertain character cue(s)")
            if report.dropped_artifacts:
                notes.append(f"{len(report.dropped_artifacts)} page-furniture line(s) removed")
        note = ("; ".join(notes) + ".") if notes else ""
        self.result_label.setText(f"Exported to {out_path}. {note}")

    def _on_failed(self, job, detail: str) -> None:
        if job is not self._job:
            return
        self._job = None
        self.export_btn.setEnabled(True)
        self.result_label.setText("Export failed.")
        QMessageBox.critical(self, "Export failed", detail.splitlines()[0])
