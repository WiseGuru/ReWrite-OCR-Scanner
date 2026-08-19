"""Persistent page thumbnail strip with per-page badges for classification,
flag severity, and review status."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from rewriteocr.core.models import Flag, PageRecord
from rewriteocr.ui.state import ProjectContext, pil_to_qpixmap

THUMB_SIZE = QSize(96, 124)

CLASS_BADGE = {"born_digital": ("T", "#2e7d32"), "scanned": ("S", "#1565c0"),
               "mixed": ("M", "#6a1b9a")}
REVIEW_BADGE = {"reviewed": ("✓", "#2e7d32"), "needs_work": ("!", "#c62828")}


def severity_color(severity: float) -> QColor:
    if severity >= 0.7:
        return QColor("#c62828")
    if severity >= 0.4:
        return QColor("#ef6c00")
    return QColor("#f9a825")


class _ThumbnailLoader(QThread):
    thumb_ready = Signal(int, QPixmap)

    def __init__(self, context: ProjectContext, count: int) -> None:
        super().__init__()
        self._context = context
        self._count = count

    def run(self) -> None:
        doc = self._context.doc
        if doc is None:
            return
        for i in range(self._count):
            if self.isInterruptionRequested():
                return
            try:
                img = doc.render_page(i, 40, 0)
            except Exception:
                continue
            self.thumb_ready.emit(i, pil_to_qpixmap(img))
            # Yield between pages: rendering back-to-back re-acquires the
            # global PDFium lock in a tight loop and starves the GUI thread
            # (which needs the same lock and the event queue), freezing the
            # window mid-layout for the whole thumbnail pass.
            self.msleep(20)


class PageStrip(QListWidget):
    page_selected = Signal(int)

    def __init__(self, context: ProjectContext) -> None:
        super().__init__()
        self.context = context
        self.setViewMode(QListWidget.IconMode)
        self.setIconSize(THUMB_SIZE)
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setUniformItemSizes(True)
        self.setSpacing(4)
        self.setFixedWidth(150)
        self._loader: _ThumbnailLoader | None = None
        self._base_thumbs: dict[int, QPixmap] = {}

        self.currentRowChanged.connect(
            lambda row: self.page_selected.emit(row) if row >= 0 else None
        )
        context.project_opened.connect(self.reload)
        context.project_closed.connect(self._clear_all)
        context.page_updated.connect(self.refresh_page)

    def _clear_all(self) -> None:
        self._stop_loader()
        self._base_thumbs.clear()
        self.clear()

    def _stop_loader(self) -> None:
        if self._loader is not None:
            self._loader.requestInterruption()
            self._loader.wait(5000)
            self._loader = None

    def reload(self) -> None:
        self._clear_all()
        if not self.context.is_open:
            return
        pages = self.context.db.get_pages()
        for page in pages:
            item = QListWidgetItem(f"p. {page.page_index + 1}")
            item.setTextAlignment(Qt.AlignHCenter)
            self.addItem(item)
            self._decorate(item, page, self.context.db.flags_for_page(page.page_index))
        self._loader = _ThumbnailLoader(self.context, len(pages))
        self._loader.thumb_ready.connect(self._on_thumb)
        self._loader.start()

    def _on_thumb(self, index: int, pixmap: QPixmap) -> None:
        self._base_thumbs[index] = pixmap
        self.refresh_page(index)

    def refresh_page(self, index: int) -> None:
        if not self.context.is_open or index >= self.count():
            return
        item = self.item(index)
        page = self.context.db.get_page(index)
        flags = self.context.db.flags_for_page(index)
        self._decorate(item, page, flags)

    def _decorate(self, item: QListWidgetItem, page: PageRecord, flags: list[Flag]) -> None:
        base = self._base_thumbs.get(page.page_index)
        canvas = QPixmap(THUMB_SIZE)
        canvas.fill(QColor("#f5f5f5"))
        painter = QPainter(canvas)
        if base is not None:
            scaled = base.scaled(THUMB_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter.drawPixmap(
                (THUMB_SIZE.width() - scaled.width()) // 2,
                (THUMB_SIZE.height() - scaled.height()) // 2,
                scaled,
            )
        letter, color = CLASS_BADGE.get(page.classification, ("?", "#555"))
        self._badge(painter, 2, 2, letter, color)
        if flags:
            worst = max(f.severity for f in flags)
            painter.setBrush(severity_color(worst))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(THUMB_SIZE.width() - 18, 4, 12, 12)
        mark = REVIEW_BADGE.get(page.review_status)
        if mark:
            self._badge(painter, THUMB_SIZE.width() - 18, THUMB_SIZE.height() - 18,
                        mark[0], mark[1])
        painter.end()
        item.setIcon(QIcon(canvas))

        tips = [f"Page {page.page_index + 1}: {page.classification.replace('_', ' ')}"]
        if page.extracted_text is not None:
            tips.append(f"extracted ({page.engine_used})")
        if page.edited_text is not None:
            tips.append("edited by you")
        tips.extend(f.detail for f in flags)
        if page.review_status != "unreviewed":
            tips.append(page.review_status.replace("_", " "))
        item.setToolTip("\n".join(tips))

    @staticmethod
    def _badge(painter: QPainter, x: int, y: int, letter: str, color: str) -> None:
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        painter.drawRect(x, y, 14, 14)
        painter.setPen(QColor("white"))
        painter.drawText(x, y, 14, 14, Qt.AlignCenter, letter)

    def select_page(self, index: int) -> None:
        if 0 <= index < self.count():
            self.setCurrentRow(index)
