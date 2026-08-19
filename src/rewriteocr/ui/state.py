"""Shared project context for the UI: open document, sidecar access from the
GUI thread, model selection, render cache, and the job queue."""

from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtGui import QImage, QPixmap

from rewriteocr.config import Settings
from rewriteocr.constants import PAGE_PIXMAP_CACHE_SIZE, THUMBNAIL_DPI
from rewriteocr.core.pdf_io import PdfDocument
from rewriteocr.core.preprocess import apply_deskew
from rewriteocr.core.sidecar import SidecarDB
from rewriteocr.engines.probe import EnvironmentStatus, probe_environment
from rewriteocr.jobs.queue import JobQueue
from rewriteocr.modelmgr import store
from rewriteocr.modelmgr.manifest import ModelSpec, load_manifest

log = logging.getLogger("rewriteocr.ui")


def pil_to_qimage(img: Image.Image) -> QImage:
    """QImage is safe to build on any thread; QPixmap is GUI-thread-only.
    Worker threads must hand over QImages and let the GUI convert."""
    rgb = img.convert("RGB")
    return QImage(
        rgb.tobytes(), rgb.width, rgb.height, rgb.width * 3, QImage.Format_RGB888
    ).copy()


def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    return QPixmap.fromImage(pil_to_qimage(img))


class _PageRenderWorker(QObject):
    """Renders pages off the GUI thread. Synchronous renders on the GUI
    thread block a tab's first layout pass, which paints its widgets
    overlapping at the top-left until the render finishes."""

    rendered = Signal(object, int, float, bool, QImage)  # doc id, index, dpi, deskewed

    @Slot(object, int, float, bool, int, float)
    def render(
        self, doc, index: int, dpi: float, deskewed: bool,
        rotation: int, deskew_angle: float,
    ) -> None:
        from rewriteocr.core.pdf_io import PdfError

        try:
            img = doc.render_page(index, dpi, rotation)
            if deskewed and deskew_angle:
                img = apply_deskew(img, deskew_angle)
            self.rendered.emit(id(doc), index, dpi, deskewed, pil_to_qimage(img))
        except PdfError:
            pass  # document closed mid-request; the result is unwanted anyway
        except Exception as exc:
            log.warning("Page render failed (page %d): %s", index, exc)


class ProjectContext(QObject):
    project_opened = Signal()
    project_closed = Signal()
    page_updated = Signal(int)
    regions_changed = Signal()
    model_status_changed = Signal()
    device_changed = Signal(str)
    status_message = Signal(str)
    # A previously requested page render is now in the cache.
    page_render_ready = Signal(int, float)  # index, dpi
    # Background pdfium work should stand down: the GUI thread is about to
    # take the global lock itself and must not queue behind a render pass.
    quiesce_requested = Signal()
    _render_request = Signal(object, int, float, bool, int, float)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.settings = Settings()
        self.jobs = JobQueue(self)
        self.env: EnvironmentStatus = probe_environment(
            self.settings.get("llama_server_path"), self.settings.get("tesseract_path")
        )
        self.manifest: list[ModelSpec] = load_manifest()

        self.pdf_path: Path | None = None
        self.password: str | None = None
        self.sidecar_path: Path | None = None
        self.db: SidecarDB | None = None
        self.doc: PdfDocument | None = None
        self.read_only = False
        self.device = "none"

        self._render_cache: OrderedDict[tuple, QPixmap] = OrderedDict()
        self._pending_renders: set[tuple] = set()
        self._render_thread = QThread(self)
        self._render_thread.setObjectName("rewriteocr-renders")
        self._render_worker = _PageRenderWorker()
        self._render_worker.moveToThread(self._render_thread)
        self._render_request.connect(self._render_worker.render)
        self._render_worker.rendered.connect(self._on_worker_rendered)
        self._render_thread.start()

    # -- project lifecycle ---------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self.db is not None and self.doc is not None

    def attach_project(
        self,
        pdf_path: Path,
        sidecar_path: Path,
        password: str | None,
        read_only: bool = False,
    ) -> None:
        self.close_project()
        self.pdf_path = pdf_path
        self.password = password
        self.sidecar_path = sidecar_path
        self.doc = PdfDocument(pdf_path, password=password)
        self.db = SidecarDB(sidecar_path)
        self.read_only = read_only
        self._render_cache.clear()
        self.project_opened.emit()

    def quiesce_background_work(self) -> None:
        """Ask background pdfium users (the thumbnail loader) to stop before
        the GUI thread blocks on the same lock."""
        self.quiesce_requested.emit()

    def close_project(self) -> None:
        if self.db is None and self.doc is None:
            # Nothing open: staying silent keeps project_closed to one
            # emission per open, since both ImportTab and attach_project call
            # this on the way in.
            return
        if self.db is not None:
            self.db.close()
        if self.doc is not None:
            self.doc.close()
        self.db = None
        self.doc = None
        self.pdf_path = None
        self.sidecar_path = None
        self._render_cache.clear()
        self._pending_renders.clear()
        self.project_closed.emit()

    # -- model selection -----------------------------------------------------

    def selected_model(self) -> tuple[ModelSpec, str] | None:
        """The active model spec and quant, when its files are installed."""
        model_id = self.settings.get("model_id")
        quant = self.settings.get("quant_name")
        candidates = (
            [m for m in self.manifest if m.id == model_id] if model_id else []
        ) + self.manifest
        for spec in candidates:
            installed = store.installed_quants(spec)
            if not installed:
                continue
            names = [q.name for q in installed]
            chosen = quant if quant in names else names[0]
            return spec, chosen
        return None

    def set_selected_model(self, model_id: str, quant_name: str) -> None:
        self.settings.set("model_id", model_id)
        self.settings.set("quant_name", quant_name)
        self.model_status_changed.emit()

    # -- rendering -----------------------------------------------------------

    def _render_key(self, index: int, dpi: float, deskewed: bool) -> tuple:
        page = self.db.get_page(index)
        return (index, round(dpi, 1), page.rotation, round(page.deskew_angle, 2), deskewed)

    def _cache_put(self, key: tuple, pixmap: QPixmap) -> None:
        self._render_cache[key] = pixmap
        while len(self._render_cache) > PAGE_PIXMAP_CACHE_SIZE:
            self._render_cache.popitem(last=False)

    def request_page_render(
        self, index: int, dpi: float = 120.0, deskewed: bool = True
    ) -> QPixmap | None:
        """Cached pixmap if available, else None with a background render
        queued; page_render_ready(index, dpi) fires when it lands. Never
        blocks the GUI thread on a render."""
        if not self.is_open:
            return None
        key = self._render_key(index, dpi, deskewed)
        cached = self._render_cache.get(key)
        if cached is not None:
            self._render_cache.move_to_end(key)
            return cached
        if key not in self._pending_renders:
            self._pending_renders.add(key)
            page = self.db.get_page(index)
            self._render_request.emit(
                self.doc, index, dpi, deskewed, page.rotation, page.deskew_angle
            )
        return None

    @Slot(object, int, float, bool, QImage)
    def _on_worker_rendered(
        self, doc_token, index: int, dpi: float, deskewed: bool, image: QImage
    ) -> None:
        if not self.is_open or doc_token != id(self.doc):
            return  # result from a document that has since been closed
        key = self._render_key(index, dpi, deskewed)
        self._pending_renders.discard(key)
        self._cache_put(key, QPixmap.fromImage(image))
        self.page_render_ready.emit(index, dpi)

    def render_page(
        self, index: int, dpi: float = 120.0, deskewed: bool = True
    ) -> QPixmap | None:
        """Synchronous render for non-interactive callers (tests, previews
        that already run off the GUI's critical path)."""
        if not self.is_open:
            return None
        key = self._render_key(index, dpi, deskewed)
        cached = self._render_cache.get(key)
        if cached is not None:
            self._render_cache.move_to_end(key)
            return cached
        page = self.db.get_page(index)
        img = self.doc.render_page(index, dpi, page.rotation)
        if deskewed and page.deskew_angle:
            img = apply_deskew(img, page.deskew_angle)
        pixmap = pil_to_qpixmap(img)
        self._cache_put(key, pixmap)
        return pixmap

    def render_thumbnail(self, index: int) -> QPixmap | None:
        if not self.is_open:
            return None
        img = self.doc.render_page(index, THUMBNAIL_DPI, 0)
        return pil_to_qpixmap(img)

    def invalidate_renders(self, index: int | None = None) -> None:
        if index is None:
            self._render_cache.clear()
        else:
            for key in [k for k in self._render_cache if k[0] == index]:
                del self._render_cache[key]

    def shutdown(self) -> None:
        self.jobs.shutdown()
        self._render_thread.quit()
        self._render_thread.wait(10_000)
        self.close_project()
