"""Main window: five-step tab bar, persistent page strip, status bar, menus."""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import Qt, QTimer
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

log = logging.getLogger("rewriteocr.ui.window")

TAB_IMPORT, TAB_RULES, TAB_EXTRACT, TAB_REVIEW, TAB_EXPORT = range(5)
TAB_NAMES = ("Import", "Rules", "Extract", "Review", "Export")

# Set REWRITEOCR_DEBUG_TABS=1 to trace every tab transition and page
# show/hide. The single-page enforcer below warns without it; this adds the
# surrounding sequence needed to name a cause.
DEBUG_TABS = os.environ.get("REWRITEOCR_DEBUG_TABS") == "1"


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
        self._transitions: list[str] = []
        self.tabs.currentChanged.connect(self._on_current_tab_changed)
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

    # -- tab navigation ------------------------------------------------------

    def _set_tabs_enabled(self, enabled: bool) -> None:
        if not enabled and self.tabs.currentIndex() != TAB_IMPORT:
            # Disabling the current tab makes Qt pick its own replacement,
            # so it would walk the stack a page at a time on the way out.
            # Land on Import deliberately instead.
            self._go_to_tab(TAB_IMPORT)
        for i in (TAB_RULES, TAB_EXTRACT, TAB_REVIEW, TAB_EXPORT):
            self.tabs.setTabEnabled(i, enabled)

    def _go_to_tab(self, index: int) -> None:
        """The only way the app changes tabs. Guarantees the incoming page is
        laid out and that it is the only visible one."""
        self.tabs.setCurrentIndex(index)
        page = self.tabs.widget(index)
        layout = page.layout() if page is not None else None
        if layout is not None:
            # A tab shown for the first time while the GUI thread is busy can
            # miss its first layout pass and paint every child stacked at the
            # top left. Activating here makes that pass unconditional.
            layout.activate()
        self._enforce_single_page()

    def _on_current_tab_changed(self, index: int) -> None:
        name = TAB_NAMES[index] if 0 <= index < len(TAB_NAMES) else str(index)
        self._transitions.append(name)
        del self._transitions[:-12]
        if DEBUG_TABS:
            import traceback

            where = "".join(traceback.format_stack(limit=8)[:-1])
            log.info("Tab -> %s (%d)\n%s", name, index, where)
        self._enforce_single_page()
        # Also check after the current event cycle: a page can be shown by
        # something that runs later in the same turn of the loop. The context
        # object cancels the timer if the window goes away first.
        QTimer.singleShot(0, self, self._enforce_single_page)

    def _enforce_single_page(self) -> None:
        """Exactly one tab page is visible, and it is the current one.

        Qt maintains this itself, but TR-1 saw two pages visible at once with
        no hide delivered to the outgoing one. Correcting it costs a handful
        of isVisible() checks per switch, and the warning is the field
        diagnostic if it ever recurs.
        """
        current = self.tabs.currentIndex()
        if current < 0 or not self.tabs.isVisible():
            return  # nothing shown yet, or the window is on its way out
        strays = []
        for i in range(self.tabs.count()):
            page = self.tabs.widget(i)
            if page is None:
                continue
            if i != current and page.isVisible():
                strays.append(TAB_NAMES[i] if i < len(TAB_NAMES) else str(i))
                page.hide()
            elif i == current and not page.isVisible():
                page.show()
        if strays:
            log.warning(
                "Tab pages overlapped (TR-1): current=%s, also visible=%s,"
                " recent transitions=%s",
                TAB_NAMES[current] if 0 <= current < len(TAB_NAMES) else current,
                ", ".join(strays),
                " > ".join(self._transitions),
            )

    # -- project lifecycle ---------------------------------------------------

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
            self._go_to_tab(TAB_REVIEW)
            self.review_tab.refresh_after_extraction()
        else:
            self._go_to_tab(TAB_EXTRACT)

    def _on_strip_selected(self, index: int) -> None:
        if not self.context.is_open or not self.tabs.isTabEnabled(TAB_REVIEW):
            return
        if self.tabs.currentIndex() != TAB_REVIEW:
            self._go_to_tab(TAB_REVIEW)
        self.review_tab.show_page(index)

    def _on_device_changed(self, device: str) -> None:
        self.device_label.setText(f"Device: {device.upper()}")

    def _on_job_finished(self, job, _result) -> None:
        if isinstance(job, ExtractJob):
            self.review_tab.refresh_after_extraction()
            if self.tabs.currentIndex() == TAB_EXTRACT and job.opts.page_indices is None:
                self._go_to_tab(TAB_REVIEW)

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
        self.strip.shutdown()
        self.context.shutdown()
        super().closeEvent(event)
