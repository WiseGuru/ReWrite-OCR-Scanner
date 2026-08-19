"""Engine interface. UI features gate on capabilities(); nothing degrades silently."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from PIL import Image

from rewriteocr.core.models import (
    Capabilities,
    PageHints,
    PageResult,
    RegionHints,
    RegionResult,
)


class EngineError(Exception):
    """Base for engine failures that the pipeline can catch and route around."""


class EngineUnavailableError(EngineError):
    """The engine's backing binary or server is not present or not healthy."""


class EngineCrashedError(EngineError):
    """The backing process died mid-request. May trigger CPU fallback."""


@runtime_checkable
class OCREngine(Protocol):
    def capabilities(self) -> Capabilities: ...

    def extract_page(self, image: Image.Image, hints: PageHints) -> PageResult: ...

    def extract_region(self, image: Image.Image, hints: RegionHints) -> RegionResult: ...
