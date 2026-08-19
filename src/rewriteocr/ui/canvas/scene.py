"""Page scene: pixmap plus region items plus the draw-mode state machine."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene

from rewriteocr.ui.canvas.region_item import KIND_COLORS, MIN_REGION_PX


class PageScene(QGraphicsScene):
    def __init__(self, controller) -> None:
        super().__init__()
        self.controller = controller
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self.draw_kind: str | None = None
        self._rubber: QGraphicsRectItem | None = None
        self._origin: QPointF | None = None

    def set_page_pixmap(self, pixmap: QPixmap) -> None:
        if self._pixmap_item is not None:
            self.removeItem(self._pixmap_item)
        self._pixmap_item = self.addPixmap(pixmap)
        self._pixmap_item.setZValue(-1)
        self.setSceneRect(QRectF(pixmap.rect()))

    def page_bounds(self) -> QRectF | None:
        if self._pixmap_item is None:
            return None
        return self._pixmap_item.boundingRect()

    def set_draw_kind(self, kind: str | None) -> None:
        self.draw_kind = kind

    # -- drawing new regions -------------------------------------------------

    def mousePressEvent(self, event) -> None:
        under_cursor = None
        if self.views():
            under_cursor = self.itemAt(event.scenePos(), self.views()[0].transform())
        if (
            self.draw_kind
            and event.button() == Qt.LeftButton
            and self._pixmap_item is not None
            and under_cursor is self._pixmap_item
        ):
            self._origin = event.scenePos()
            color = QColor(KIND_COLORS.get(self.draw_kind, "#555"))
            pen = QPen(color, 2, Qt.DashLine)
            pen.setCosmetic(True)
            self._rubber = self.addRect(QRectF(self._origin, self._origin), pen)
            fill = QColor(color)
            fill.setAlpha(30)
            self._rubber.setBrush(QBrush(fill))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._rubber is not None and self._origin is not None:
            rect = QRectF(self._origin, event.scenePos()).normalized()
            bounds = self.page_bounds()
            if bounds is not None:
                rect = rect.intersected(bounds)
            self._rubber.setRect(rect)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._rubber is not None:
            rect = self._rubber.rect()
            self.removeItem(self._rubber)
            self._rubber = None
            self._origin = None
            if rect.width() >= MIN_REGION_PX and rect.height() >= MIN_REGION_PX:
                self.controller.create_region_from_rect(rect, self.draw_kind)
            event.accept()
            return
        super().mouseReleaseEvent(event)
