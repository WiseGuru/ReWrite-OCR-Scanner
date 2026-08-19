"""Main window: five-step tab bar, persistent page strip, status bar, menus."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QMainWindow,
    QTabWidget,
)

from rewriteocr import __version__
from rewriteocr.engines.probe import DiagnosticInfo
from rewriteocr.jobs.definitions import ExtractJob
from rewriteocr.ui.dialogs.diagnostics import AboutDialog, DiagnosticsDialog
from rewriteocr.ui.export_tab import ExportTab
from rewriteocr.ui.extract_tab import ExtractTab
from rewriteocr.ui.import_tab import ImportTab
from rewriteocr.ui.pagestrip import PageStrip
from rewriteocr.ui.review_tab import ReviewTab
from rewriteocr.ui.rules_tab import RulesTab
from rewriteocr.ui.state import ProjectContext

TAB_IMPORT, TAB_RULES, TAB_EXTRACT, TAB_REVIEW, TAB_EXPORT = range(5)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"ReWrite OCR Scanner {__version__}")
        self.resize(1280, 860)
        self.context = ProjectContext(self)

        self.tabs = QTabWidget()
        self.import_tab = ImportTab(self.context)
        self.rules_tab = RulesTab(self.context)
        self.extract_tab = ExtractTab(self.context)
        self.review_tab = ReviewTab(self.context)
        self.export_tab = ExportTab(self.context)
        self.tabs.addTab(self.import_tab, "Import")
        self.tabs.addTab(self.rules_tab, "Rules")
        self.tabs.addTab(self.extract_tab, "Extract")
        self.tabs.addTab(self.review_tab, "Review")
        self.tabs.addTab(self.export_tab, "Export")
        self.setCentralWidget(self.tabs)
        self._set_tabs_enabled(False)

        self.strip = PageStrip(self.context)
        dock = QDockWidget("Pages", self)
        dock.setWidget(self.strip)
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

        self.device_label = QLabel("")
        self.statusBar().addPermanentWidget(self.device_label)

        menu = self.menuBar().addMenu("&Help")
        menu.addAction("Copy diagnostic info...", self._show_diagnostics)
        menu.addAction("About and licenses...", self._show_about)

        ctx = self.context
        ctx.project_opened.connect(self._on_project_opened)
        ctx.project_closed.connect(lambda: self._set_tabs_enabled(False))
        ctx.device_changed.connect(self._on_device_changed)
        ctx.status_message.connect(lambda m: self.statusBar().showMessage(m, 8000))
        ctx.jobs.job_page_done.connect(lambda _job, i: ctx.page_updated.emit(i))
        ctx.jobs.job_finished.connect(self._on_job_finished)
        self.strip.page_selected.connect(self._on_strip_selected)

    def _set_tabs_enabled(self, enabled: bool) -> None:
        for i in (TAB_RULES, TAB_EXTRACT, TAB_REVIEW, TAB_EXPORT):
            self.tabs.setTabEnabled(i, enabled)

    def _on_project_opened(self) -> None:
        self._set_tabs_enabled(True)
        counts = {"scanned": 0, "mixed": 0}
        extracted = 0
        for p in self.context.db.get_pages():
            if p.classification in counts:
                counts[p.classification] += 1
            if p.extracted_text is not None:
                extracted += 1
        if extracted:
            self.tabs.setCurrentIndex(TAB_REVIEW)
            self.review_tab.refresh_after_extraction()
        else:
            self.tabs.setCurrentIndex(TAB_EXTRACT)

    def _on_strip_selected(self, index: int) -> None:
        if self.tabs.currentIndex() not in (TAB_REVIEW,):
            self.tabs.setCurrentIndex(TAB_REVIEW)
        self.review_tab.show_page(index)

    def _on_device_changed(self, device: str) -> None:
        self.device_label.setText(f"Device: {device.upper()}")

    def _on_job_finished(self, job, _result) -> None:
        if isinstance(job, ExtractJob):
            self.review_tab.refresh_after_extraction()
            if self.tabs.currentIndex() == TAB_EXTRACT and job.opts.page_indices is None:
                self.tabs.setCurrentIndex(TAB_REVIEW)

    def _show_diagnostics(self) -> None:
        info = DiagnosticInfo(device=self.context.device)
        selected = self.context.selected_model()
        if selected:
            spec, quant = selected
            info.model_id = spec.id
            info.model_revision = spec.revision
            info.quant = quant
        review_page = self.review_tab._current_page
        if review_page is not None and self.context.is_open:
            info.page_flags = [
                f"p{review_page + 1}:{f.kind}:{f.severity:.2f}"
                for f in self.context.db.flags_for_page(review_page)
            ]
        DiagnosticsDialog(info, self.context.env, self).exec()

    def _show_about(self) -> None:
        AboutDialog(self).exec()

    def closeEvent(self, event) -> None:
        self.context.shutdown()
        super().closeEvent(event)
