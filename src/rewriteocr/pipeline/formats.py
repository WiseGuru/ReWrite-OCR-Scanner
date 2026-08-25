"""The export format registry.

One row per format carrying everything the UI and the job need: the label,
the file suffix, the save-dialog filter and the callable. Before this, the
suffix was hardcoded in three places in the export tab and the dispatch was a
two-branch if in the job, so adding a format meant editing four sites and
silently falling back to Markdown if one was missed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rewriteocr.core.models import ExportFormat, ExportOptions, StitchLog
from rewriteocr.core.sidecar import SidecarDB
from rewriteocr.pipeline.export_docx import export_docx
from rewriteocr.pipeline.export_md import export_markdown
from rewriteocr.pipeline.export_screenplay import (
    export_fdx,
    export_fountain,
    export_screenplay_docx,
)

# (sidecar, pdf_path, out_path, options) -> StitchLog. The source PDF is
# passed because the screenplay classifier re-derives glyph geometry from it
# for born-digital pages; prose exporters ignore it.
Exporter = Callable[[SidecarDB, "Path | None", Path, ExportOptions], StitchLog]


def _prose(fn: Callable[[SidecarDB, Path, ExportOptions], StitchLog]) -> Exporter:
    """Adapt a prose exporter, which has no use for the source PDF, onto the
    registry signature. Keeps export_md and export_docx untouched."""

    def call(
        sidecar: SidecarDB, pdf_path: Path | None, out_path: Path, options: ExportOptions
    ) -> StitchLog:
        return fn(sidecar, out_path, options)

    return call


@dataclass(frozen=True)
class ExportFormatSpec:
    key: ExportFormat
    label: str
    suffix: str
    file_filter: str
    screenplay: bool
    exporter: Exporter


EXPORT_FORMATS: tuple[ExportFormatSpec, ...] = (
    ExportFormatSpec(
        key="markdown",
        label="Markdown (.md)",
        suffix=".md",
        file_filter="Markdown (*.md)",
        screenplay=False,
        exporter=_prose(export_markdown),
    ),
    ExportFormatSpec(
        key="docx",
        label="Word (.docx)",
        suffix=".docx",
        file_filter="Word document (*.docx)",
        screenplay=False,
        exporter=_prose(export_docx),
    ),
    ExportFormatSpec(
        key="fountain",
        label="Fountain screenplay (.fountain)",
        suffix=".fountain",
        file_filter="Fountain screenplay (*.fountain)",
        screenplay=True,
        exporter=export_fountain,
    ),
    ExportFormatSpec(
        key="fdx",
        label="Final Draft (.fdx)",
        suffix=".fdx",
        file_filter="Final Draft (*.fdx)",
        screenplay=True,
        exporter=export_fdx,
    ),
    ExportFormatSpec(
        key="screenplay_docx",
        label="Screenplay Word (.docx)",
        suffix=".docx",
        file_filter="Word document (*.docx)",
        screenplay=True,
        exporter=export_screenplay_docx,
    ),
)

_BY_KEY = {spec.key: spec for spec in EXPORT_FORMATS}


def format_spec(key: str) -> ExportFormatSpec:
    try:
        return _BY_KEY[key]
    except KeyError:
        raise ValueError(f"Unknown export format: {key!r}") from None


def formats_for_mode(document_mode: str) -> tuple[ExportFormatSpec, ...]:
    """Screenplay formats are offered only for a screenplay project. The mode
    is set at import and changeable from the export tab, so this is never a
    dead end."""
    if document_mode == "screenplay":
        return EXPORT_FORMATS
    return tuple(spec for spec in EXPORT_FORMATS if not spec.screenplay)
