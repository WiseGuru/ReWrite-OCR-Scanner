"""Per-page extraction orchestration: dispatch by classification, apply
regions, run the parallel Tesseract cross-check, compute flags, and commit
each page in its own transaction.

Pure logic with callback reporting; the job layer wraps this in Qt signals.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from PIL import Image

from rewriteocr.core import figures as figures_mod
from rewriteocr.core.flags import (
    engine_disagreement_flag,
    low_yield_flag,
    repetition_flag,
)
from rewriteocr.core.models import (
    FigureRef,
    Flag,
    PageHints,
    PageRecord,
    Region,
    RegionHints,
)
from rewriteocr.core.normalize import normalize_markdown
from rewriteocr.core.pdf_io import PdfDocument, PdfPageDamagedError
from rewriteocr.core.preprocess import estimate_skew, ink_ratio, prepare_model_image
from rewriteocr.core.rules import (
    filter_glyphs_excluding,
    glyphs_in_region,
    glyphs_to_text,
    regions_for_page,
)
from rewriteocr.core.sidecar import SidecarDB
from rewriteocr.core.triage import classify_page
from rewriteocr.engines.base import EngineCrashedError, EngineError
from rewriteocr.engines.llama_server import LlamaServerManager
from rewriteocr.engines.tesseract_engine import TesseractEngine
from rewriteocr.engines.vlm_engine import VLMEngine
from rewriteocr.jobs.control import JobControl
from rewriteocr.modelmgr import store
from rewriteocr.modelmgr.manifest import ModelSpec

log = logging.getLogger("rewriteocr.pipeline")

TEXT_LAYER_ENGINE_ID = "text_layer"
MAX_CRASH_RESTARTS = 2
DEFAULT_RENDER_DPI = 200


class Reporter(Protocol):
    def progress(self, done: int, total: int, eta_s: float | None) -> None: ...

    def page_done(self, page_index: int) -> None: ...

    def device_changed(self, device: str) -> None: ...

    def message(self, text: str) -> None: ...


class NullReporter:
    def progress(self, done: int, total: int, eta_s: float | None) -> None: ...

    def page_done(self, page_index: int) -> None: ...

    def device_changed(self, device: str) -> None: ...

    def message(self, text: str) -> None: ...


@dataclass
class ExtractOptions:
    spec: ModelSpec | None = None  # None: no VLM available (text layer + Tesseract only)
    quant_name: str | None = None
    engine: str = "auto"  # 'auto' | 'tesseract'
    page_indices: list[int] | None = None  # None: every page without extracted_text
    clear_edited: bool = False
    repeat_penalty_override: float | None = None
    figures_dir: Path | None = None


@dataclass
class ExtractStats:
    pages_done: int = 0
    pages_failed: list[int] = field(default_factory=list)
    device_fallback: bool = False
    engine_switches: list[int] = field(default_factory=list)


def run_triage(
    pdf_path: Path,
    sidecar: SidecarDB,
    control: JobControl,
    reporter: Reporter,
    password: str | None = None,
) -> list[PageRecord]:
    """Classify every page and populate the pages table."""
    with PdfDocument(pdf_path, password=password) as doc:
        records: list[PageRecord] = []
        for i in range(doc.page_count):
            control.checkpoint()
            w, h = doc.page_size_pt(i)
            try:
                result = classify_page(doc, i)
                classification = result.classification
            except PdfPageDamagedError:
                classification = "scanned"
            records.append(
                PageRecord(
                    page_index=i,
                    classification=classification,
                    width_pt=w,
                    height_pt=h,
                )
            )
            reporter.progress(i + 1, doc.page_count, None)
        sidecar.insert_pages(records)
        return records


@dataclass
class _EngineSet:
    vlm: VLMEngine | None
    tesseract: TesseractEngine | None
    manager: LlamaServerManager | None


def _region_sort_key(r: Region):
    return (r.order_index, r.id or 0)


def _mask_regions(image: Image.Image, regions: list[Region]) -> Image.Image:
    """Paint excluded areas white so the VLM never sees them."""
    if not regions:
        return image
    out = image.copy()
    for r in regions:
        rn = r.normalized()
        box = (
            round(rn.x0 * out.width),
            round(rn.y0 * out.height),
            round(rn.x1 * out.width),
            round(rn.y1 * out.height),
        )
        out.paste("white", box)
    return out


class _PageExtractor:
    def __init__(
        self,
        doc: PdfDocument,
        sidecar: SidecarDB,
        regions: list[Region],
        engines: _EngineSet,
        opts: ExtractOptions,
        control: JobControl,
        reporter: Reporter,
        stats: ExtractStats,
    ) -> None:
        self.doc = doc
        self.sidecar = sidecar
        self.regions = regions
        self.engines = engines
        self.opts = opts
        self.control = control
        self.reporter = reporter
        self.stats = stats
        self.render_dpi = opts.spec.preprocess.dpi if opts.spec else DEFAULT_RENDER_DPI
        self._tess_pool = ThreadPoolExecutor(max_workers=1) if engines.tesseract else None

    def close(self) -> None:
        if self._tess_pool:
            self._tess_pool.shutdown(wait=False, cancel_futures=True)

    # -- helpers -------------------------------------------------------------

    def _model_meta(self) -> tuple[str | None, str | None]:
        if self.opts.spec:
            return self.opts.spec.id, self.opts.spec.revision
        return None, None

    def _render_for_model(self, page: PageRecord) -> tuple[Image.Image, float]:
        rendered = self.doc.render_page(page.page_index, self.render_dpi, page.rotation)
        angle = page.deskew_angle
        if page.classification != "born_digital" and angle == 0.0:
            angle = estimate_skew(rendered)
            if angle:
                self.sidecar.set_deskew_angle(page.page_index, angle)
        if self.opts.spec:
            image = prepare_model_image(rendered, angle, self.opts.spec.preprocess)
        else:
            image = prepare_model_image_no_spec(rendered, angle)
        return image, angle

    def _figures_dir(self) -> Path:
        if self.opts.figures_dir:
            return self.opts.figures_dir
        return self.sidecar.path.parent / (self.sidecar.path.stem + "_figures")

    def _choose_region_engine(
        self, image: Image.Image, region: Region, page_index: int
    ):
        """VLMs loop on very short fragments; below min_region_lines the
        region routes to Tesseract. Never silent: recorded in stats and
        reported."""
        vlm, tess = self.engines.vlm, self.engines.tesseract
        if vlm is None:
            return tess
        if tess is None:
            return vlm
        min_lines = vlm.capabilities().min_region_lines
        if min_lines <= 0 or region.kind in ("table", "figure"):
            return vlm
        rn = region.normalized()
        try:
            n_lines = tess.count_lines_in_region(image, rn.x0, rn.y0, rn.x1, rn.y1)
        except EngineError:
            return vlm
        if n_lines < min_lines:
            if page_index not in self.stats.engine_switches:
                self.stats.engine_switches.append(page_index)
            self.reporter.message(
                f"Page {page_index + 1}: a small region was read with Tesseract"
                f" because it has fewer than {min_lines} text lines."
            )
            return tess
        return vlm

    # -- born-digital path ---------------------------------------------------

    def extract_born_digital(self, page: PageRecord) -> str:
        idx = page.page_index
        page_regions = regions_for_page(self.regions, idx)
        glyphs = self.doc.page_glyphs(idx)

        if not page_regions:
            text = self.doc.page_text(idx).replace("\r\n", "\n").replace("\r", "\n")
            return normalize_markdown(text)

        kept = filter_glyphs_excluding(glyphs, page_regions)
        ordered = [r for r in page_regions if r.kind in ("column", "heading", "table", "figure")]
        parts: list[str] = []
        consumed_regions = []
        figure_seq = 0
        rendered: Image.Image | None = None
        for region in sorted(ordered, key=_region_sort_key):
            if region.kind == "figure":
                if rendered is None:
                    rendered = self.doc.render_page(idx, self.render_dpi, page.rotation)
                figure_seq += 1
                rel = figures_mod.save_figure(
                    rendered, region, self._figures_dir(), idx, figure_seq
                )
                self.sidecar.add_figure(
                    FigureRef(page_index=idx, file_path=rel, region_id=region.id)
                )
                parts.append(f"![Figure]({rel})")
                consumed_regions.append(region)
                continue
            selected = glyphs_in_region(kept, region)
            text = glyphs_to_text(selected)
            if not text:
                consumed_regions.append(region)
                continue
            if region.kind == "heading":
                level = region.heading_level or 1
                text = "#" * level + " " + " ".join(text.split())
            parts.append(text)
            consumed_regions.append(region)

        if ordered:
            # Explicit regions define the content; anything outside a drawn
            # column/heading/table/figure region but inside no exclude region
            # is appended afterward so nothing is silently lost.
            leftover = kept
            for region in consumed_regions:
                selected = set(id(g) for g in glyphs_in_region(kept, region))
                leftover = [g for g in leftover if id(g) not in selected]
            tail = glyphs_to_text(leftover)
            if tail:
                parts.append(tail)
            return normalize_markdown("\n\n".join(p for p in parts if p))

        # Exclusions only: rebuild text from the filtered glyph set.
        return normalize_markdown(glyphs_to_text(kept))

    # -- scanned path --------------------------------------------------------

    def extract_scanned(self, page: PageRecord) -> tuple[str, str, str | None]:
        """Returns (markdown, engine_used, tesseract_text_for_crosscheck)."""
        idx = page.page_index
        image, _ = self._render_for_model(page)
        page_regions = regions_for_page(self.regions, idx)
        excludes = [r for r in page_regions if r.kind == "exclude"]
        structural = sorted(
            [r for r in page_regions if r.kind in ("column", "heading", "table", "figure")],
            key=_region_sort_key,
        )
        # Column and heading regions mean the user has drawn the reading
        # order explicitly: only regions are transcribed, in order. Table and
        # figure regions alone are carve-outs: the rest of the page is still
        # read normally, with the carved areas masked so they are not
        # transcribed twice.
        explicit_layout = any(r.kind in ("column", "heading") for r in structural)
        masked = _mask_regions(image, excludes)

        primary = (
            self.engines.tesseract
            if (self.opts.engine == "tesseract" or self.engines.vlm is None)
            else self.engines.vlm
        )
        if primary is None:
            raise EngineError(
                "No OCR engine is available for scanned pages. Download a model"
                " or install Tesseract."
            )

        cross_future: Future | None = None
        if (
            self._tess_pool is not None
            and primary is self.engines.vlm
            and self.engines.tesseract is not None
        ):
            tess = self.engines.tesseract
            cross_future = self._tess_pool.submit(
                lambda: tess.extract_page(masked, PageHints(page_index=idx)).markdown
            )

        engines_used: list[str] = []
        if structural and not explicit_layout:
            # Page-level read with table and figure areas masked out, then
            # the carve-outs appended in their explicit order.
            page_masked = _mask_regions(masked, structural)
            hints = PageHints(
                page_index=idx, repeat_penalty_override=self.opts.repeat_penalty_override
            )
            result = self._run_with_crash_fallback(
                lambda: primary.extract_page(page_masked, hints)
            )
            parts = [normalize_markdown(result.markdown)]
            engines_used.append(result.engine_id)
            figure_seq = 0
            for region in structural:
                self.control.checkpoint()
                if region.kind == "figure":
                    figure_seq += 1
                    rel = figures_mod.save_figure(
                        image, region, self._figures_dir(), idx, figure_seq
                    )
                    self.sidecar.add_figure(
                        FigureRef(page_index=idx, file_path=rel, region_id=region.id)
                    )
                    parts.append(f"![Figure]({rel})")
                    continue
                crop = figures_mod.crop_region(masked, region)
                engine = self._choose_region_engine(masked, region, idx)
                region_hints = RegionHints(page_index=idx, kind="table")
                r = self._run_with_crash_fallback(
                    lambda e=engine, c=crop, h=region_hints: e.extract_region(c, h)
                )
                text = normalize_markdown(r.markdown)
                if text:
                    parts.append(text)
                if r.engine_id not in engines_used:
                    engines_used.append(r.engine_id)
            markdown = "\n\n".join(p for p in parts if p)
        elif structural:
            parts: list[str] = []
            figure_seq = 0
            for region in structural:
                self.control.checkpoint()
                if region.kind == "figure":
                    figure_seq += 1
                    rel = figures_mod.save_figure(
                        image, region, self._figures_dir(), idx, figure_seq
                    )
                    self.sidecar.add_figure(
                        FigureRef(page_index=idx, file_path=rel, region_id=region.id)
                    )
                    parts.append(f"![Figure]({rel})")
                    continue
                crop = figures_mod.crop_region(masked, region)
                engine = self._choose_region_engine(masked, region, idx)
                hints = RegionHints(
                    page_index=idx,
                    kind=region.kind if region.kind == "table" else "column",
                    heading_level=region.heading_level,
                )
                result = self._run_with_crash_fallback(
                    lambda e=engine, c=crop, h=hints: e.extract_region(c, h)
                )
                text = normalize_markdown(result.markdown)
                if region.kind == "heading" and text:
                    level = region.heading_level or 1
                    text = "#" * level + " " + " ".join(text.split())
                if text:
                    parts.append(text)
                if result.engine_id not in engines_used:
                    engines_used.append(result.engine_id)
            markdown = "\n\n".join(parts)
        else:
            hints = PageHints(
                page_index=idx, repeat_penalty_override=self.opts.repeat_penalty_override
            )
            result = self._run_with_crash_fallback(
                lambda: primary.extract_page(masked, hints)
            )
            markdown = normalize_markdown(result.markdown)
            engines_used.append(result.engine_id)

        cross_text: str | None = None
        if cross_future is not None:
            try:
                cross_text = cross_future.result(timeout=300)
            except Exception as exc:  # cross-check is advisory, never fatal
                log.warning("Tesseract cross-check failed on page %d: %s", idx, exc)
        return markdown, "+".join(engines_used), cross_text

    def _run_with_crash_fallback(self, call):
        """On a dead server (OOM or crash), drop to CPU and retry, up to the
        restart cap. The run is flagged via stats.device_fallback."""
        attempts = 0
        while True:
            try:
                return call()
            except EngineCrashedError as exc:
                attempts += 1
                manager = self.engines.manager
                if manager is None or attempts > MAX_CRASH_RESTARTS:
                    raise
                log.warning("Engine crashed (%s); restarting on CPU", exc)
                self.reporter.message(
                    "The model backend stopped responding; continuing on CPU."
                )
                manager.start_cpu()
                self.stats.device_fallback = True
                self.reporter.device_changed("cpu")

    # -- flags ---------------------------------------------------------------

    def compute_flags(
        self, page: PageRecord, markdown: str, cross_text: str | None
    ) -> list[Flag]:
        flags: list[Flag] = []
        idx = page.page_index
        rep = repetition_flag(idx, markdown)
        if rep:
            flags.append(rep)
        if page.classification != "born_digital":
            try:
                rendered = self.doc.render_page(idx, self.render_dpi, page.rotation)
                ratio = ink_ratio(rendered)
                ly = low_yield_flag(idx, markdown, ratio, rendered.width * rendered.height)
                if ly:
                    flags.append(ly)
            except PdfPageDamagedError:
                pass
        if cross_text:
            dis = engine_disagreement_flag(idx, markdown, cross_text)
            if dis:
                flags.append(dis)
        return flags


def prepare_model_image_no_spec(rendered: Image.Image, deskew_angle: float) -> Image.Image:
    from rewriteocr.core.preprocess import apply_deskew

    return apply_deskew(rendered, deskew_angle)


def extract_document(
    pdf_path: Path,
    sidecar: SidecarDB,
    opts: ExtractOptions,
    control: JobControl,
    reporter: Reporter,
    password: str | None = None,
) -> ExtractStats:
    """Extract the selected pages, committing each page atomically."""
    stats = ExtractStats()
    pages = sidecar.get_pages()
    if opts.page_indices is not None:
        wanted = set(opts.page_indices)
        targets = [p for p in pages if p.page_index in wanted]
    else:
        targets = [p for p in pages if p.extracted_text is None]
    if not targets:
        reporter.message("Nothing to extract.")
        return stats

    regions = sidecar.list_regions()
    needs_model = any(p.classification != "born_digital" for p in targets)

    manager: LlamaServerManager | None = None
    vlm: VLMEngine | None = None
    from rewriteocr.engines.tesseract_engine import find_tesseract

    tess_path = find_tesseract()
    tesseract = TesseractEngine(tess_path) if tess_path else None

    try:
        if needs_model and opts.spec and opts.engine != "tesseract":
            quant = opts.spec.quant(opts.quant_name or opts.spec.quants[0].name)
            manager = LlamaServerManager(
                model_path=store.quant_path(opts.spec, quant),
                mmproj_path=store.mmproj_path(opts.spec),
                context_size=opts.spec.context_size,
            )
            reporter.message(f"Starting {opts.spec.display_name}...")
            manager.start()
            reporter.device_changed(manager.device)
            if manager.device == "cpu":
                stats.device_fallback = True
            vlm = VLMEngine(opts.spec, manager)

        with PdfDocument(pdf_path, password=password) as doc:
            engines = _EngineSet(vlm=vlm, tesseract=tesseract, manager=manager)
            extractor = _PageExtractor(
                doc, sidecar, regions, engines, opts, control, reporter, stats
            )
            durations: dict[str, list[float]] = {"born": [], "scanned": []}
            try:
                for n, page in enumerate(targets):
                    control.checkpoint()
                    started = time.monotonic()
                    model_id, model_rev = (None, None)
                    try:
                        if page.classification == "born_digital":
                            markdown = extractor.extract_born_digital(page)
                            engine_used = TEXT_LAYER_ENGINE_ID
                            cross = None
                        else:
                            markdown, engine_used, cross = extractor.extract_scanned(page)
                            if engine_used.startswith("vlm:") and opts.spec:
                                model_id, model_rev = opts.spec.id, opts.spec.revision
                        flags = extractor.compute_flags(page, markdown, cross)
                        sidecar.write_page_result(
                            page.page_index, markdown, engine_used, model_id, model_rev,
                            flags, clear_edited=opts.clear_edited,
                        )
                        stats.pages_done += 1
                    except (PdfPageDamagedError, EngineError) as exc:
                        log.error("Page %d failed: %s", page.page_index, exc)
                        stats.pages_failed.append(page.page_index)
                        reporter.message(f"Page {page.page_index + 1} failed: {exc}")
                    finally:
                        kind = "born" if page.classification == "born_digital" else "scanned"
                        durations[kind].append(time.monotonic() - started)
                    reporter.page_done(page.page_index)
                    eta = _estimate_eta(targets[n + 1 :], durations)
                    reporter.progress(n + 1, len(targets), eta)
            finally:
                extractor.close()
    finally:
        if manager is not None:
            manager.stop()
    return stats


def _estimate_eta(
    remaining: list[PageRecord], durations: dict[str, list[float]]
) -> float | None:
    def avg(kind: str, fallback: float) -> float:
        vals = durations[kind]
        return sum(vals) / len(vals) if vals else fallback

    if not remaining:
        return 0.0
    if not durations["born"] and not durations["scanned"]:
        return None
    born_avg = avg("born", 0.2)
    scanned_avg = avg("scanned", 10.0)
    return sum(
        born_avg if p.classification == "born_digital" else scanned_avg for p in remaining
    )
