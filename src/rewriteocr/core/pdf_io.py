"""pypdfium2 wrapper. The only module that touches PDFium directly.

Coordinates: PDFium uses points with origin at the bottom-left. Everything
this module returns is normalized to 0.0-1.0 of the page box with origin at
the TOP-left, matching the region model and Qt's image coordinates.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from PIL import Image


class PdfError(Exception):
    pass


class PdfPasswordError(PdfError):
    """Encrypted document: no password given or the given one is wrong."""


class PdfPageDamagedError(PdfError):
    """A specific page could not be loaded or rendered."""


@dataclass(frozen=True)
class GlyphBox:
    """One character with its normalized top-left-origin bounding box."""

    char: str
    x0: float
    y0: float
    x1: float
    y1: float


def sha256_of_file(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


# PDFium is not thread-safe, even across separate documents. Every call into
# pdfium anywhere in the process must hold this one lock.
_PDFIUM_LOCK = threading.RLock()


class PdfDocument:
    """Owns a pdfium handle. All pdfium calls are serialized through the
    module-global lock so the UI thread (thumbnails) and worker thread
    (extraction) can each hold their own instance safely."""

    def __init__(self, path: str | Path, password: str | None = None) -> None:
        self.path = Path(path)
        self._lock = _PDFIUM_LOCK
        self._closed = False
        with self._lock:
            try:
                self._doc = pdfium.PdfDocument(str(self.path), password=password)
            except pdfium.PdfiumError as exc:
                if "password" in str(exc).lower():
                    raise PdfPasswordError(str(exc)) from exc
                raise PdfError(f"Could not open PDF: {exc}") from exc
            self.page_count = len(self._doc)

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._doc.close()

    def _check_open(self) -> None:
        if self._closed:
            raise PdfError("Document is closed.")

    def __enter__(self) -> PdfDocument:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def page_size_pt(self, index: int) -> tuple[float, float]:
        with self._lock:
            self._check_open()
            page = self._doc[index]
            try:
                return page.get_size()
            finally:
                page.close()

    def page_text(self, index: int) -> str:
        with self._lock:
            self._check_open()
            page = self._doc[index]
            try:
                textpage = page.get_textpage()
                try:
                    text = textpage.get_text_range()
                    # PDFium marks a line-wrap hyphen with U+FFFE and drops
                    # the break; restore both so downstream heuristics
                    # (hyphen rejoin) see what the page shows.
                    return text.replace("￾", "-\r\n")
                finally:
                    textpage.close()
            except pdfium.PdfiumError as exc:
                raise PdfPageDamagedError(f"Text extraction failed on page {index}: {exc}") from exc
            finally:
                page.close()

    def page_glyphs(self, index: int) -> list[GlyphBox]:
        """Every character with its normalized box, for exclusion filtering
        and text-coverage measurement."""
        with self._lock:
            self._check_open()
            page = self._doc[index]
            try:
                w, h = page.get_size()
                textpage = page.get_textpage()
                try:
                    glyphs: list[GlyphBox] = []
                    n = textpage.count_chars()
                    text = textpage.get_text_range() if n else ""
                    for i in range(n):
                        left, bottom, right, top = textpage.get_charbox(i)
                        ch = text[i] if i < len(text) else ""
                        if ch == "￾":
                            ch = "-"
                        glyphs.append(
                            GlyphBox(
                                char=ch,
                                x0=left / w,
                                y0=1.0 - top / h,
                                x1=right / w,
                                y1=1.0 - bottom / h,
                            )
                        )
                    return glyphs
                finally:
                    textpage.close()
            except pdfium.PdfiumError as exc:
                raise PdfPageDamagedError(f"Glyph read failed on page {index}: {exc}") from exc
            finally:
                page.close()

    def page_image_boxes(self, index: int) -> list[tuple[float, float, float, float]]:
        """Normalized boxes of embedded image objects, for mixed-page triage."""
        with self._lock:
            self._check_open()
            page = self._doc[index]
            try:
                w, h = page.get_size()
                boxes = []
                for obj in page.get_objects(filter=(pdfium_c.FPDF_PAGEOBJ_IMAGE,), max_depth=2):
                    try:
                        left, bottom, right, top = obj.get_bounds()
                    except pdfium.PdfiumError:
                        continue
                    boxes.append(
                        (left / w, 1.0 - top / h, right / w, 1.0 - bottom / h)
                    )
                return boxes
            except pdfium.PdfiumError as exc:
                raise PdfPageDamagedError(f"Object scan failed on page {index}: {exc}") from exc
            finally:
                page.close()

    def render_page(
        self, index: int, dpi: float, rotation: int = 0, grayscale: bool = False
    ) -> Image.Image:
        """Render at the given DPI. rotation is the user override (0/90/180/270)."""
        with self._lock:
            self._check_open()
            page = self._doc[index]
            try:
                bitmap = page.render(
                    scale=dpi / 72.0,
                    rotation=rotation,
                    grayscale=grayscale,
                )
                try:
                    return bitmap.to_pil()
                finally:
                    bitmap.close()
            except pdfium.PdfiumError as exc:
                raise PdfPageDamagedError(f"Render failed on page {index}: {exc}") from exc
            finally:
                page.close()
