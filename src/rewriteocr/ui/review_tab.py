"""Review tab: split view of page image and Markdown, flag-driven ordering,
direct editing, keyboard-first navigation."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from rewriteocr.jobs.definitions import ExtractJob
from rewriteocr.pipeline.extract import ExtractOptions
from rewriteocr.ui.dialogs.annotate_dialog import AnnotateDialog
from rewriteocr.ui.pagestrip import severity_color
from rewriteocr.ui.state import ProjectContext

RETRY_PENALTY_BOOST = 0.25


class ReviewTab(QWidget):
    page_shown = Signal(int)

    def __init__(self, context: ProjectContext) -> None:
        super().__init__()
        self.context = context
        self._nav: list[int] = []
        self._pos = -1
        self._current_page: int | None = None
        self._loading = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self._save_edits)

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Show:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("Flagged pages", "flagged")
        self.filter_combo.addItem("All pages", "all")
        self.filter_combo.addItem("Needs work", "needs_work")
        top.addWidget(self.filter_combo)
        self.position_label = QLabel("")
        top.addWidget(self.position_label, 1)
        layout.addLayout(top)

        self.flag_banner = QLabel("")
        self.flag_banner.setWordWrap(True)
        self.flag_banner.setVisible(False)
        layout.addWidget(self.flag_banner)

        splitter = QSplitter(Qt.Horizontal)
        self.image_scroll = QScrollArea()
        self.image_label = QLabel("Open a document and extract to review.")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_scroll.setWidget(self.image_label)
        self.image_scroll.setWidgetResizable(True)
        splitter.addWidget(self.image_scroll)
        self.editor = QPlainTextEdit()
        self.editor.textChanged.connect(self._on_text_changed)
        splitter.addWidget(self.editor)
        splitter.setSizes([500, 500])
        layout.addWidget(splitter, 1)

        buttons = QHBoxLayout()
        self.prev_btn = QPushButton("Previous (P)")
        self.next_btn = QPushButton("Next (N)")
        self.reviewed_btn = QPushButton("Mark reviewed, next (Ctrl+Enter)")
        self.needs_work_btn = QPushButton("Needs work (Ctrl+D)")
        self.retry_btn = QPushButton("Retry (higher repeat penalty)")
        self.annotate_btn = QPushButton("Annotate and re-extract...")
        for b in (self.prev_btn, self.next_btn, self.reviewed_btn,
                  self.needs_work_btn, self.retry_btn, self.annotate_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.prev_btn.clicked.connect(lambda: self._step(-1))
        self.next_btn.clicked.connect(lambda: self._step(1))
        self.reviewed_btn.clicked.connect(self._mark_reviewed_next)
        self.needs_work_btn.clicked.connect(self._mark_needs_work)
        self.retry_btn.clicked.connect(self._retry_higher_penalty)
        self.annotate_btn.clicked.connect(self._annotate)
        self.filter_combo.currentIndexChanged.connect(self._rebuild_nav)

        QShortcut(QKeySequence("N"), self, activated=lambda: self._step(1))
        QShortcut(QKeySequence("P"), self, activated=lambda: self._step(-1))
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._mark_reviewed_next)
        QShortcut(QKeySequence("Ctrl+D"), self, activated=self._mark_needs_work)

        context.project_opened.connect(self._on_project_opened)
        context.project_closed.connect(self._on_project_closed)
        context.page_updated.connect(self._on_page_updated)
        context.page_render_ready.connect(self._on_render_ready)

    def _on_render_ready(self, index: int, dpi: float) -> None:
        if index == self._current_page and dpi == self.REVIEW_DPI:
            pixmap = self.context.request_page_render(index, dpi=self.REVIEW_DPI)
            if pixmap is not None:
                self.image_label.setText("")
                self.image_label.setPixmap(pixmap)

    # -- navigation ----------------------------------------------------------

    def _on_project_opened(self) -> None:
        self._current_page = None
        self._rebuild_nav()

    def _on_project_closed(self) -> None:
        self._nav = []
        self._pos = -1
        self._current_page = None
        self.editor.clear()
        self.image_label.clear()
        self.image_label.setText("Open a document and extract to review.")

    def _default_filter(self) -> None:
        """Default to flagged-only when flags exist, per spec."""
        if self.context.is_open and self.context.db.all_flags():
            self.filter_combo.setCurrentIndex(0)
        else:
            self.filter_combo.setCurrentIndex(1)

    def _rebuild_nav(self) -> None:
        if not self.context.is_open:
            return
        mode = self.filter_combo.currentData()
        db = self.context.db
        if mode == "flagged":
            worst: dict[int, float] = {}
            for f in db.all_flags():
                worst[f.page_index] = max(worst.get(f.page_index, 0.0), f.severity)
            self._nav = [i for i, _ in sorted(worst.items(), key=lambda kv: -kv[1])]
        elif mode == "needs_work":
            self._nav = [
                p.page_index for p in db.get_pages() if p.review_status == "needs_work"
            ]
        else:
            self._nav = [p.page_index for p in db.get_pages()]
        if self._current_page in self._nav:
            self._pos = self._nav.index(self._current_page)
        else:
            self._pos = 0 if self._nav else -1
            if self._nav:
                self._show_page(self._nav[0])
        self._update_position_label()

    def _step(self, delta: int) -> None:
        if not self._nav:
            return
        self._save_edits()
        self._pos = max(0, min(len(self._nav) - 1, self._pos + delta))
        self._show_page(self._nav[self._pos])

    def show_page(self, index: int) -> None:
        """External entry (page strip click)."""
        if not self.context.is_open:
            return
        self._save_edits()
        if index in self._nav:
            self._pos = self._nav.index(index)
        self._show_page(index)

    REVIEW_DPI = 110.0

    def _show_page(self, index: int) -> None:
        self._current_page = index
        page = self.context.db.get_page(index)
        pixmap = self.context.request_page_render(index, dpi=self.REVIEW_DPI)
        if pixmap is not None:
            self.image_label.setPixmap(pixmap)
        else:
            self.image_label.clear()
            self.image_label.setText("Rendering page...")
        self._loading = True
        self.editor.setPlainText(page.effective_text or "")
        self.editor.setReadOnly(self.context.read_only or page.extracted_text is None)
        self._loading = False
        flags = self.context.db.flags_for_page(index)
        if flags:
            worst = max(f.severity for f in flags)
            color = severity_color(worst).name()
            self.flag_banner.setStyleSheet(
                f"background: {color}; color: white; padding: 6px; border-radius: 3px;"
            )
            self.flag_banner.setText(" ".join(f.detail for f in flags))
            self.flag_banner.setVisible(True)
        else:
            self.flag_banner.setVisible(False)
        self.retry_btn.setEnabled(
            any(f.kind == "repetition" for f in flags)
            and self.context.selected_model() is not None
            and not self.context.read_only
        )
        self._update_position_label()
        self.page_shown.emit(index)

    def _update_position_label(self) -> None:
        mode = self.filter_combo.currentText().lower()
        if self._current_page is None or not self._nav:
            self.position_label.setText(f"No {mode}.")
            return
        self.position_label.setText(
            f"Page {self._current_page + 1}: {self._pos + 1} of {len(self._nav)} {mode}"
        )

    # -- editing -------------------------------------------------------------

    def _on_text_changed(self) -> None:
        if not self._loading and self._current_page is not None:
            self._save_timer.start()

    def _save_edits(self) -> None:
        self._save_timer.stop()
        if (
            self._current_page is None
            or not self.context.is_open
            or self.context.read_only
            or self.editor.isReadOnly()
        ):
            return
        page = self.context.db.get_page(self._current_page)
        text = self.editor.toPlainText()
        if text == (page.effective_text or ""):
            return
        # Matching the engine output exactly clears the override.
        new_value = None if text == (page.extracted_text or "") else text
        self.context.db.set_edited_text(self._current_page, new_value)
        self.context.page_updated.emit(self._current_page)

    # -- review actions ------------------------------------------------------

    def _mark_reviewed_next(self) -> None:
        if self._current_page is None or self.context.read_only:
            return
        self._save_edits()
        self.context.db.set_review_status(self._current_page, "reviewed")
        self.context.page_updated.emit(self._current_page)
        self._step(1)

    def _mark_needs_work(self) -> None:
        if self._current_page is None or self.context.read_only:
            return
        self._save_edits()
        self.context.db.set_review_status(self._current_page, "needs_work")
        self.context.page_updated.emit(self._current_page)

    def _confirm_overwrite_edits(self, index: int) -> bool:
        page = self.context.db.get_page(index)
        if page.edited_text is None:
            return True
        answer = QMessageBox.question(
            self, "Overwrite your edits?",
            f"Page {index + 1} has text you edited. Re-extracting will replace"
            " it with fresh engine output.",
            QMessageBox.Yes | QMessageBox.Cancel,
        )
        return answer == QMessageBox.Yes

    def _submit_reextract(self, index: int, repeat_penalty: float | None) -> None:
        selected = self.context.selected_model()
        opts = ExtractOptions(
            page_indices=[index],
            clear_edited=True,
            repeat_penalty_override=repeat_penalty,
        )
        if selected:
            opts.spec, opts.quant_name = selected
        self.context.jobs.submit(
            ExtractJob(
                self.context.pdf_path, self.context.sidecar_path, opts,
                password=self.context.password,
            )
        )

    def _retry_higher_penalty(self) -> None:
        if self._current_page is None or not self._confirm_overwrite_edits(self._current_page):
            return
        selected = self.context.selected_model()
        if selected is None:
            return
        spec, _ = selected
        boosted = spec.sampling.repeat_penalty + RETRY_PENALTY_BOOST
        self._submit_reextract(self._current_page, boosted)

    def _annotate(self) -> None:
        if self._current_page is None or not self.context.is_open:
            return
        self._save_edits()
        dialog = AnnotateDialog(self.context, self._current_page, self)
        if dialog.exec() and dialog.wants_reextract:
            if self._confirm_overwrite_edits(self._current_page):
                self._submit_reextract(self._current_page, None)

    # -- updates from jobs ---------------------------------------------------

    def _on_page_updated(self, index: int) -> None:
        if index == self._current_page:
            page = self.context.db.get_page(index)
            if not self.editor.hasFocus():
                self._loading = True
                self.editor.setPlainText(page.effective_text or "")
                self.editor.setReadOnly(
                    self.context.read_only or page.extracted_text is None
                )
                self._loading = False

    def refresh_after_extraction(self) -> None:
        self._default_filter()
        self._rebuild_nav()
