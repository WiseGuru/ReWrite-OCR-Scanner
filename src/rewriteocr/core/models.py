"""Core dataclasses shared across pipeline, engines, and UI. No Qt imports here."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Classification = Literal["born_digital", "scanned", "mixed"]
ReviewStatus = Literal["unreviewed", "reviewed", "needs_work"]
RegionKind = Literal["exclude", "table", "figure", "column", "heading"]
RegionScope = Literal["all", "odd", "even", "range", "single"]


@dataclass
class PageRecord:
    page_index: int
    classification: Classification
    width_pt: float
    height_pt: float
    deskew_angle: float = 0.0
    rotation: int = 0
    review_status: ReviewStatus = "unreviewed"
    extracted_text: str | None = None
    edited_text: str | None = None
    engine_used: str | None = None
    model_id: str | None = None
    model_revision: str | None = None
    extracted_at: str | None = None

    @property
    def effective_text(self) -> str | None:
        """User edit wins; NULL edit means use the engine output."""
        return self.edited_text if self.edited_text is not None else self.extracted_text


@dataclass
class Region:
    scope: RegionScope
    kind: RegionKind
    order_index: int
    x0: float
    y0: float
    x1: float
    y1: float
    scope_arg: str | None = None
    heading_level: int | None = None
    id: int | None = None
    created_at: str | None = None

    def normalized(self) -> Region:
        """Return a copy with corner ordering fixed so x0<=x1 and y0<=y1."""
        x0, x1 = sorted((self.x0, self.x1))
        y0, y1 = sorted((self.y0, self.y1))
        out = Region(**{**self.__dict__})
        out.x0, out.y0, out.x1, out.y1 = x0, y0, x1, y1
        return out


FlagKind = Literal["repetition", "low_yield", "engine_disagreement"]


@dataclass
class Flag:
    page_index: int
    kind: FlagKind
    severity: float
    detail: str = ""


@dataclass
class Capabilities:
    region_conditioned: bool
    layout_detection: bool
    bbox_output: bool
    min_region_lines: int
    output_format: Literal["markdown", "html", "json"]


@dataclass
class PageHints:
    page_index: int = 0
    # Per-request sampling override used by the "retry at higher repeat penalty" action.
    repeat_penalty_override: float | None = None


@dataclass
class RegionHints:
    page_index: int = 0
    kind: RegionKind = "column"
    heading_level: int | None = None


@dataclass
class PageResult:
    markdown: str
    engine_id: str
    duration_s: float = 0.0


@dataclass
class RegionResult:
    markdown: str
    engine_id: str
    duration_s: float = 0.0


@dataclass
class TriageResult:
    classification: Classification
    text: str
    printable_ratio: float = 0.0
    alpha_ratio: float = 0.0
    text_area_frac: float = 0.0
    image_area_frac: float = 0.0


@dataclass
class FigureRef:
    page_index: int
    file_path: str
    region_id: int | None = None
    id: int | None = None


@dataclass
class ProjectInfo:
    source_hash: str
    source_filename: str
    source_page_count: int
    app_version: str
    schema_version: int
    created_at: str
    modified_at: str


@dataclass
class ExportOptions:
    fmt: Literal["markdown", "docx"] = "markdown"
    page_break: Literal["none", "comment", "rule"] = "none"
    output_path: str = ""
    stitch: bool = True


@dataclass
class StitchLog:
    hyphen_joins: list[int] = field(default_factory=list)
    headers_dropped: list[str] = field(default_factory=list)
    tables_merged: list[int] = field(default_factory=list)
