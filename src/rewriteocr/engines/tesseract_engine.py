"""Tesseract via subprocess: fallback OCR engine, cross-check source, and
text-line geometry oracle for region edge snapping.

No pytesseract dependency; the TSV output gives everything needed. Tesseract
is optional at runtime: when absent, features that depend on it are disabled
with a visible reason, never silently degraded.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from rewriteocr.core.models import (
    Capabilities,
    PageHints,
    PageResult,
    RegionHints,
    RegionResult,
)
from rewriteocr.engines.base import EngineError, EngineUnavailableError

log = logging.getLogger("rewriteocr.tesseract")

WINDOWS_DEFAULT_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)
SUBPROCESS_TIMEOUT_S = 300


def find_tesseract(settings_path: str | None = None) -> str | None:
    """Explicit setting, then PATH, then the standard Windows install dirs."""
    if settings_path and Path(settings_path).is_file():
        return settings_path
    found = shutil.which("tesseract")
    if found:
        return found
    if sys.platform == "win32":
        for p in WINDOWS_DEFAULT_PATHS:
            if Path(p).is_file():
                return p
    return None


def tesseract_version(exe: str) -> str | None:
    try:
        out = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        first = (out.stdout or out.stderr).splitlines()
        return first[0].strip() if first else None
    except (OSError, subprocess.TimeoutExpired):
        return None


@dataclass(frozen=True)
class LineBox:
    """Normalized text-line box from the layout pass."""

    x0: float
    y0: float
    x1: float
    y1: float


def snap_outward(
    x0: float, y0: float, x1: float, y1: float,
    lines: list[LineBox],
    snap_x: bool = True,
) -> tuple[float, float, float, float]:
    """Expand a normalized box outward so no detected text line is cut. A
    crop that slices a line mid-height makes the VLM invent a completion.
    Column regions pass snap_x=False because horizontal cuts there are the
    user's explicit intent."""
    for line in lines:
        if line.x0 < x1 and line.x1 > x0 and line.y0 < y1 and line.y1 > y0:
            y0 = min(y0, line.y0)
            y1 = max(y1, line.y1)
            if snap_x:
                x0 = min(x0, line.x0)
                x1 = max(x1, line.x1)
    return (max(0.0, x0), max(0.0, y0), min(1.0, x1), min(1.0, y1))


class TesseractEngine:
    """OCREngine backed by the tesseract binary. Also exposes line_boxes(),
    the geometry oracle used for snapping region edges to text lines."""

    engine_id = "tesseract"

    def __init__(self, exe: str, lang: str = "eng") -> None:
        self.exe = exe
        self.lang = lang

    def capabilities(self) -> Capabilities:
        return Capabilities(
            region_conditioned=True,
            layout_detection=False,
            bbox_output=False,
            min_region_lines=0,
            output_format="markdown",
        )

    def _run(self, image: Image.Image, config: list[str]) -> str:
        from rewriteocr.config import temp_dir

        with tempfile.TemporaryDirectory(prefix="tess_", dir=temp_dir()) as td:
            img_path = os.path.join(td, "page.png")
            image.save(img_path, format="PNG")
            cmd = [self.exe, img_path, "stdout", "-l", self.lang, *config]
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=SUBPROCESS_TIMEOUT_S,
                    creationflags=(
                        subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                    ),
                )
            except FileNotFoundError as exc:
                raise EngineUnavailableError(f"tesseract not found at {self.exe}") from exc
            except subprocess.TimeoutExpired as exc:
                raise EngineError("tesseract timed out") from exc
            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="replace")[:500]
                raise EngineError(f"tesseract failed (code {result.returncode}): {stderr}")
            return result.stdout.decode("utf-8", errors="replace")

    def extract_page(self, image: Image.Image, hints: PageHints) -> PageResult:
        text = self._run(image, ["--psm", "3"]).strip()
        return PageResult(markdown=text, engine_id=self.engine_id)

    def extract_region(self, image: Image.Image, hints: RegionHints) -> RegionResult:
        # PSM 6: assume a uniform block of text, right for crops.
        text = self._run(image, ["--psm", "6"]).strip()
        return RegionResult(markdown=text, engine_id=self.engine_id)

    def line_boxes(self, image: Image.Image) -> list[LineBox]:
        """Text-line bounding boxes, normalized to the image. Level 4 rows in
        the TSV are lines."""
        tsv = self._run(image, ["--psm", "3", "tsv"])
        boxes: list[LineBox] = []
        w, h = image.width, image.height
        for row in tsv.splitlines()[1:]:
            parts = row.split("\t")
            if len(parts) < 10:
                continue
            try:
                level = int(parts[0])
                left, top = int(parts[6]), int(parts[7])
                width, height = int(parts[8]), int(parts[9])
            except ValueError:
                continue
            if level != 4 or width <= 0 or height <= 0:
                continue
            boxes.append(
                LineBox(x0=left / w, y0=top / h, x1=(left + width) / w, y1=(top + height) / h)
            )
        return boxes

    def count_lines_in_region(
        self, image: Image.Image, x0: float, y0: float, x1: float, y1: float
    ) -> int:
        """How many detected text lines intersect the given normalized box.
        Drives the min_region_lines auto-switch to Tesseract."""
        count = 0
        for box in self.line_boxes(image):
            if box.x0 < x1 and box.x1 > x0 and box.y0 < y1 and box.y1 > y0:
                count += 1
        return count
