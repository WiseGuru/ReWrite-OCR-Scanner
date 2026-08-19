"""Region rectangle item with kind coloring, an explicit order badge, and
resize handles. Order is always shown; it is never inferred from geometry."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPen
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
)

KIND_COLORS = {
    "exclude": "#c62828",
    "table": "#1565c0",
    "figure": "#6a1b9a",
    "column": "#2e7d32",
    "heading": "#ef6c00",
}
HANDLE_SIZE = 8.0
MIN_REGION_PX = 8.0


class HandleItem(QGraphicsRectItem):
    """One of eight resize handles. Position code: (dx, dy) in {-1, 0, 1}."""

    def __init__(self, parent: RegionItem, code: tuple[int, int]) -> None:
        s = HANDLE_SIZE
        super().__init__(-s / 2, -s / 2, s, s, parent)
        self.code = code
        self.setBrush(QBrush(QColor("white")))
        self.setPen(QPen(QColor("#333"), 1))
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setAcceptedMouseButtons(Qt.LeftButton)
        cursors = {
            (-1, -1): Qt.SizeFDiagCursor, (1, 1): Qt.SizeFDiagCursor,
            (1, -1): Qt.SizeBDiagCursor, (-1, 1): Qt.SizeBDiagCursor,
            (0, -1): Qt.SizeVerCursor, (0, 1): Qt.SizeVerCursor,
            (-1, 0): Qt.SizeHorCursor, (1, 0): Qt.SizeHorCursor,
        }
        self.setCursor(cursors[code])
        self._dragging = False

    def mousePressEvent(self, event) -> None:
        self._dragging = True
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._dragging:
            return
        parent: RegionItem = self.parentItem()
        parent.resize_by_handle(self.code, self.mapToParent(event.pos()))
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False
        parent: RegionItem = self.parentItem()
        parent.commit_geometry()
        event.accept()


class RegionItem(QGraphicsRectItem):
    """The rect lives in item coordinates; the item's pos is its offset in
    the scene. Controller callbacks fire on committed geometry changes."""

    def __init__(self, region_id: int, kind: str, rect: QRectF, controller) -> None:
        super().__init__(QRectF(0, 0, rect.width(), rect.height()))
        self.setPos(rect.topLeft())
        self.region_id = region_id
        self.kind = kind
        self.controller = controller
        color = QColor(KIND_COLORS.get(kind, "#555"))
        pen = QPen(color, 2)
        pen.setCosmetic(True)
        self.setPen(pen)
        fill = QColor(color)
        fill.setAlpha(40)
        self.setBrush(QBrush(fill))
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptedMouseButtons(Qt.LeftButton)

        self._badge = QGraphicsSimpleTextItem("", self)
        self._badge.setBrush(QBrush(QColor("white")))
        font = QFont()
        font.setBold(True)
        font.setPointSize(10)
        self._badge.setFont(font)
        self._badge_bg = QGraphicsRectItem(self)
        self._badge_bg.setBrush(QBrush(color))
        self._badge_bg.setPen(QPen(Qt.NoPen))
        self._badge.setZValue(2)
        self._badge_bg.setZValue(1)
        self._badge.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self._badge_bg.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)

        self._handles = [
            HandleItem(self, (dx, dy))
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            if not (dx == 0 and dy == 0)
        ]
        self._layout_children()
        self.set_handles_visible(False)

    # -- appearance ----------------------------------------------------------

    def set_order_label(self, text: str) -> None:
        self._badge.setText(text)
        rect = self._badge.boundingRect().adjusted(-3, -1, 3, 1)
        self._badge_bg.setRect(rect)
        self._layout_children()

    def set_handles_visible(self, visible: bool) -> None:
        for h in self._handles:
            h.setVisible(visible)

    def _layout_children(self) -> None:
        r = self.rect()
        self._badge.setPos(r.left() + 4, r.top() + 2)
        self._badge_bg.setPos(r.left() + 4, r.top() + 2)
        for h in self._handles:
            dx, dy = h.code
            x = {(-1): r.left(), 0: r.center().x(), 1: r.right()}[dx]
            y = {(-1): r.top(), 0: r.center().y(), 1: r.bottom()}[dy]
            h.setPos(x, y)

    # -- geometry ------------------------------------------------------------

    def scene_rect(self) -> QRectF:
        return QRectF(self.pos(), self.rect().size())

    def resize_by_handle(self, code: tuple[int, int], point: QPointF) -> None:
        r = self.rect()
        dx, dy = code
        left, top, right, bottom = r.left(), r.top(), r.right(), r.bottom()
        if dx == -1:
            left = min(point.x(), right - MIN_REGION_PX)
        elif dx == 1:
            right = max(point.x(), left + MIN_REGION_PX)
        if dy == -1:
            top = min(point.y(), bottom - MIN_REGION_PX)
        elif dy == 1:
            bottom = max(point.y(), top + MIN_REGION_PX)
        new = QRectF(QPointF(left, top), QPointF(right, bottom)).normalized()
        # Re-anchor so the item rect starts at (0, 0) again.
        self.setPos(self.pos() + new.topLeft())
        self.setRect(QRectF(0, 0, new.width(), new.height()))
        self._layout_children()

    def commit_geometry(self) -> None:
        self.controller.item_geometry_committed(self)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedChange:
            self.set_handles_visible(bool(value))
        elif change == QGraphicsItem.ItemPositionChange and self.scene() is not None:
            # Clamp inside the page pixmap.
            bounds = self.controller.page_bounds()
            if bounds is not None:
                r = self.rect()
                x = min(max(value.x(), bounds.left()), bounds.right() - r.width())
                y = min(max(value.y(), bounds.top()), bounds.bottom() - r.height())
                return QPointF(x, y)
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        self.commit_geometry()
