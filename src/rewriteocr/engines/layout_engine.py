"""Layout detection interface. v1 ships only the null implementation: the
PP-DocLayout-V3 integration (auto-proposed regions) is deferred, and this
interface is the seam it will plug into without a refactor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PIL import Image


@dataclass(frozen=True)
class LayoutRegion:
    kind: str  # 'text' | 'title' | 'table' | 'figure' | 'header' | 'footer'
    confidence: float
    x0: float
    y0: float
    x1: float
    y1: float


class LayoutEngine(Protocol):
    def detect(self, image: Image.Image) -> list[LayoutRegion]: ...

    def available(self) -> bool: ...


class NullLayoutEngine:
    """No layout model installed. Callers must gate features on available()."""

    def detect(self, image: Image.Image) -> list[LayoutRegion]:
        return []

    def available(self) -> bool:
        return False
