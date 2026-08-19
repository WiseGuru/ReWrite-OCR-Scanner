"""Markdown export: the canonical output. DOCX renders from this, never
independently.

Figures live next to the sidecar during extraction; export copies them to
<output-stem>_figures/ and rewrites references so the output folder is
self-contained.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from rewriteocr.core.models import ExportOptions, StitchLog
from rewriteocr.core.sidecar import SidecarDB
from rewriteocr.core.stitching import stitch_pages

PAGE_BREAK_COMMENT = "<!-- page break -->"
PAGE_BREAK_RULE = "\n---\n"


def collect_page_texts(sidecar: SidecarDB) -> list[str]:
    """Effective text per page, empty string for unextracted pages."""
    return [p.effective_text or "" for p in sidecar.get_pages()]


def assemble_markdown(
    pages: list[str], options: ExportOptions
) -> tuple[str, StitchLog]:
    if options.stitch:
        pages, log = stitch_pages(list(pages))
    else:
        log = StitchLog()
    nonempty = [(i, p) for i, p in enumerate(pages) if p.strip()]
    if options.page_break == "comment":
        joined = ("\n\n" + PAGE_BREAK_COMMENT + "\n\n").join(p for _, p in nonempty)
    elif options.page_break == "rule":
        joined = ("\n" + PAGE_BREAK_RULE + "\n").join(p for _, p in nonempty)
    else:
        joined = "\n\n".join(p for _, p in nonempty)
    return joined.strip() + "\n", log


def _figures_source_dir(sidecar: SidecarDB) -> Path:
    return sidecar.path.parent / (sidecar.path.stem + "_figures")


def export_markdown(
    sidecar: SidecarDB, out_path: Path, options: ExportOptions
) -> StitchLog:
    pages = collect_page_texts(sidecar)
    markdown, log = assemble_markdown(pages, options)

    src_figs = _figures_source_dir(sidecar)
    if src_figs.is_dir() and any(src_figs.iterdir()):
        dest_figs = out_path.parent / (out_path.stem + "_figures")
        dest_figs.mkdir(parents=True, exist_ok=True)
        for f in src_figs.iterdir():
            if f.is_file():
                shutil.copy2(f, dest_figs / f.name)
        markdown = re.sub(
            rf"\]\({re.escape(src_figs.name)}/",
            f"]({dest_figs.name}/",
            markdown,
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")
    return log
