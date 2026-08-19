"""Shared project context for the UI: open document, sidecar access from the
GUI thread, model selection, render cache, and the job queue."""

from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QObject, Signal
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


class ProjectContext(QObject):
    project_opened = Signal()
    project_closed = Signal()
    page_updated = Signal(int)
    regions_changed = Signal()
    model_status_changed = Signal()
    device_changed = Signal(str)
    status_message = Signal(str)

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

    def close_project(self) -> None:
        if self.db is not None:
            self.db.close()
        if self.doc is not None:
            self.doc.close()
        self.db = None
        self.doc = None
        self.pdf_path = None
        self.sidecar_path = None
        self._render_cache.clear()
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

    def render_page(
        self, index: int, dpi: float = 120.0, deskewed: bool = True
    ) -> QPixmap | None:
        """Cached page render honoring rotation override and stored deskew."""
        if not self.is_open:
            return None
        page = self.db.get_page(index)
        key = (index, round(dpi, 1), page.rotation, round(page.deskew_angle, 2), deskewed)
        cached = self._render_cache.get(key)
        if cached is not None:
            self._render_cache.move_to_end(key)
            return cached
        img = self.doc.render_page(index, dpi, page.rotation)
        if deskewed and page.deskew_angle:
            img = apply_deskew(img, page.deskew_angle)
        pixmap = pil_to_qpixmap(img)
        self._render_cache[key] = pixmap
        while len(self._render_cache) > PAGE_PIXMAP_CACHE_SIZE:
            self._render_cache.popitem(last=False)
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
        self.close_project()
