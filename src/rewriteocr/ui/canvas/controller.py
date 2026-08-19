"""Region controller: the testable brain between canvas items and the region
model. Converts scene pixels to normalized page coordinates at this boundary
and persists every committed change to the sidecar."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, QRectF, Signal

from rewriteocr.core.models import Region
from rewriteocr.core.rules import regions_for_page
from rewriteocr.engines.tesseract_engine import (
    LineBox,
    TesseractEngine,
    find_tesseract,
    snap_outward,
)
from rewriteocr.ui.canvas.region_item import RegionItem
from rewriteocr.ui.canvas.scene import PageScene
from rewriteocr.ui.state import ProjectContext

log = logging.getLogger("rewriteocr.canvas")


class RegionController(QObject):
    """One controller per canvas. mode 'global' creates regions with the
    scope chosen by scope_provider; mode 'page' pins them to one page."""

    regions_edited = Signal()
    selection_changed = Signal(object)  # Region | None
    page_displayed = Signal(int)  # the canvas now shows this page's render

    def __init__(
        self,
        context: ProjectContext,
        mode: str = "global",
        scope_provider: Callable[[], tuple[str, str | None]] | None = None,
        heading_level_provider: Callable[[], int] | None = None,
    ) -> None:
        super().__init__()
        self.context = context
        self.mode = mode
        self.scope_provider = scope_provider
        self.heading_level_provider = heading_level_provider
        self.scene = PageScene(self)
        self.page_index: int | None = None
        self.snap_enabled = True
        self._items: dict[int, RegionItem] = {}  # region id -> item
        self._line_boxes: list[LineBox] | None = None
        self.scene.selectionChanged.connect(self._on_selection)
        context.page_render_ready.connect(self._on_render_ready)

    # -- page handling -------------------------------------------------------

    CANVAS_DPI = 120.0

    def set_page(self, page_index: int) -> None:
        """Asynchronous: the pixmap appears when the background render
        lands and page_displayed fires. Rendering here on the GUI thread
        blocked a tab's first layout pass and painted it scrambled."""
        self.page_index = page_index
        self._line_boxes = None
        pixmap = self.context.request_page_render(page_index, dpi=self.CANVAS_DPI)
        if pixmap is not None:
            self._apply_pixmap(pixmap)

    def _on_render_ready(self, index: int, dpi: float) -> None:
        if index == self.page_index and dpi == self.CANVAS_DPI:
            pixmap = self.context.request_page_render(index, dpi=self.CANVAS_DPI)
            if pixmap is not None:
                self._apply_pixmap(pixmap)

    def _apply_pixmap(self, pixmap) -> None:
        self.scene.set_page_pixmap(pixmap)
        self.reload_regions()
        self._start_line_box_prefetch()
        self.page_displayed.emit(self.page_index)

    def reload_regions(self) -> None:
        for item in self._items.values():
            self.scene.removeItem(item)
        self._items.clear()
        if self.page_index is None or not self.context.is_open:
            return
        regions = regions_for_page(self.context.db.list_regions(), self.page_index)
        bounds = self.scene.page_bounds()
        if bounds is None:
            return
        for region in regions:
            rect = QRectF(
                region.x0 * bounds.width(),
                region.y0 * bounds.height(),
                (region.x1 - region.x0) * bounds.width(),
                (region.y1 - region.y0) * bounds.height(),
            )
            item = RegionItem(region.id, region.kind, rect, self)
            self.scene.addItem(item)
            self._items[region.id] = item
        self._renumber()

    def page_bounds(self) -> QRectF | None:
        return self.scene.page_bounds()

    # -- creation and editing ------------------------------------------------

    def set_draw_kind(self, kind: str | None) -> None:
        self.scene.set_draw_kind(kind)

    def create_region_from_rect(self, rect: QRectF, kind: str) -> None:
        if self.page_index is None or self.context.read_only:
            return
        bounds = self.scene.page_bounds()
        if bounds is None or bounds.width() < 1:
            return
        x0, y0 = rect.left() / bounds.width(), rect.top() / bounds.height()
        x1, y1 = rect.right() / bounds.width(), rect.bottom() / bounds.height()
        if self.snap_enabled and kind != "exclude":
            x0, y0, x1, y1 = self._snap(x0, y0, x1, y1, kind)
        if self.mode == "page":
            scope, scope_arg = "single", str(self.page_index + 1)
        else:
            scope, scope_arg = (
                self.scope_provider() if self.scope_provider else ("all", None)
            )
        heading_level = None
        if kind == "heading":
            heading_level = (
                self.heading_level_provider() if self.heading_level_provider else 1
            )
        existing = self.context.db.list_regions()
        region = Region(
            scope=scope, scope_arg=scope_arg, kind=kind,
            heading_level=heading_level,
            order_index=(max((r.order_index for r in existing), default=-1) + 1),
            x0=x0, y0=y0, x1=x1, y1=y1,
        )
        region.id = self.context.db.add_region(region)
        self.reload_regions()
        self._emit_changed()

    def item_geometry_committed(self, item: RegionItem) -> None:
        if self.context.read_only:
            return
        bounds = self.scene.page_bounds()
        if bounds is None:
            return
        region = self._find_region(item.region_id)
        if region is None:
            return
        r = item.scene_rect()
        region.x0 = max(0.0, r.left() / bounds.width())
        region.y0 = max(0.0, r.top() / bounds.height())
        region.x1 = min(1.0, r.right() / bounds.width())
        region.y1 = min(1.0, r.bottom() / bounds.height())
        self.context.db.update_region(region)
        self._emit_changed()

    def delete_selected(self) -> None:
        if self.context.read_only:
            return
        for item in list(self.scene.selectedItems()):
            if isinstance(item, RegionItem):
                self.context.db.delete_region(item.region_id)
        self.reload_regions()
        self._emit_changed()

    def move_selected(self, delta: int) -> None:
        """Swap order_index with the neighbor in that direction."""
        if self.context.read_only:
            return
        selected = self.selected_region()
        if selected is None:
            return
        regions = sorted(
            self.context.db.list_regions(), key=lambda r: (r.order_index, r.id or 0)
        )
        idx = next((i for i, r in enumerate(regions) if r.id == selected.id), None)
        if idx is None:
            return
        other = idx + delta
        if not 0 <= other < len(regions):
            return
        a, b = regions[idx], regions[other]
        a.order_index, b.order_index = b.order_index, a.order_index
        self.context.db.update_region(a)
        self.context.db.update_region(b)
        self.reload_regions()
        self._emit_changed()

    def selected_region(self) -> Region | None:
        for item in self.scene.selectedItems():
            if isinstance(item, RegionItem):
                return self._find_region(item.region_id)
        return None

    # -- internals -----------------------------------------------------------

    def _find_region(self, region_id: int) -> Region | None:
        for r in self.context.db.list_regions():
            if r.id == region_id:
                return r
        return None

    def _renumber(self) -> None:
        if self.page_index is None:
            return
        ordered = regions_for_page(self.context.db.list_regions(), self.page_index)
        for n, region in enumerate(ordered, start=1):
            item = self._items.get(region.id)
            if item is not None:
                item.set_order_label(f"{n} {region.kind}")

    def _snap(self, x0, y0, x1, y1, kind) -> tuple[float, float, float, float]:
        boxes = self._line_boxes
        if not boxes:
            # Prefetch has not finished (or Tesseract is absent): create the
            # region unsnapped rather than stalling the GUI on a subprocess.
            return x0, y0, x1, y1
        return snap_outward(x0, y0, x1, y1, boxes, snap_x=(kind != "column"))

    def _start_line_box_prefetch(self) -> None:
        """Compute Tesseract line boxes in the background so region drawing
        can snap without ever blocking the GUI thread. Page data is captured
        here because the worker must not touch the GUI thread's SidecarDB."""
        if not self.snap_enabled or self.page_index is None or not self.context.is_open:
            return
        exe = self.context.env.tesseract_path or find_tesseract()
        if exe is None:
            return
        page = self.context.db.get_page(self.page_index)
        doc = self.context.doc
        page_index = self.page_index

        def work() -> None:
            try:
                img = doc.render_page(page_index, 150, page.rotation)
                if page.deskew_angle:
                    from rewriteocr.core.preprocess import apply_deskew

                    img = apply_deskew(img, page.deskew_angle)
                boxes = TesseractEngine(exe).line_boxes(img)
            except Exception as exc:
                log.warning("Line-box detection failed: %s", exc)
                return
            if self.page_index == page_index:
                self._line_boxes = boxes

        threading.Thread(target=work, name="line-box-prefetch", daemon=True).start()

    def _on_selection(self) -> None:
        self.selection_changed.emit(self.selected_region())

    def _emit_changed(self) -> None:
        self.regions_edited.emit()
        self.context.regions_changed.emit()
