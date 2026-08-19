"""Integration test: real llama-server spawn, identity check, one OCR call,
teardown with no orphaned process. Requires downloaded GLM-OCR weights and
llama-server on PATH. Run explicitly with: pytest -m integration"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from rewriteocr.core.models import PageHints
from rewriteocr.engines.llama_server import LlamaServerManager, ServerState
from rewriteocr.engines.vlm_engine import VLMEngine
from rewriteocr.modelmgr import store
from rewriteocr.modelmgr.manifest import get_model

pytestmark = pytest.mark.integration

TEST_SENTENCE = "The quick brown fox jumps over the lazy dog."


def _test_page_image() -> Image.Image:
    img = Image.new("RGB", (1200, 800), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=36)
    draw.text((80, 80), "Integration Test Page", fill="black", font=font)
    draw.text((80, 200), TEST_SENTENCE, fill="black", font=font)
    return img


@pytest.fixture(scope="module")
def glm_spec():
    spec = get_model("glm-ocr-0.9b")
    quant = spec.quant("Q8_0")
    if shutil.which("llama-server") is None:
        pytest.skip("llama-server not on PATH")
    if not store.is_quant_installed(spec, quant):
        pytest.skip("GLM-OCR Q8_0 weights not downloaded")
    return spec, quant


def test_scanned_page_with_regions(glm_spec, tmp_path):
    """Full pipeline on a scanned page: exclude region masked out, figure
    region cropped to a file, and the rest read by the real model."""
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    from conftest import make_scanned_pdf

    from rewriteocr.core.models import Region
    from rewriteocr.core.pdf_io import sha256_of_file
    from rewriteocr.core.sidecar import SidecarDB
    from rewriteocr.jobs.control import JobControl
    from rewriteocr.pipeline.extract import (
        ExtractOptions,
        NullReporter,
        extract_document,
        run_triage,
    )

    spec, quant = glm_spec
    pdf = make_scanned_pdf(tmp_path / "regions.pdf", n_pages=1)
    with SidecarDB(tmp_path / "regions.ocrproj") as db:
        db.initialize(sha256_of_file(pdf), "regions.pdf", 1)
        run_triage(pdf, db, JobControl(), NullReporter())
        # Exclude the title band; the fixture titles sit in the top 12 percent.
        db.add_region(Region(scope="all", kind="exclude", order_index=0,
                             x0=0.0, y0=0.0, x1=1.0, y1=0.12))
        # Figure region over the lower half.
        db.add_region(Region(scope="all", kind="figure", order_index=1,
                             x0=0.05, y0=0.55, x1=0.95, y1=0.95))
        opts = ExtractOptions(spec=spec, quant_name=quant.name)
        stats = extract_document(pdf, db, opts, JobControl(), NullReporter())
        assert stats.pages_done == 1, stats
        page = db.get_page(0)
        text = page.extracted_text.lower()
        assert "scanned page" not in text, "excluded region leaked into output"
        assert "quick brown fox" in text
        assert "![figure](" in text
        figs = db.figures_for_page(0)
        assert len(figs) == 1
        fig_path = db.path.parent / figs[0].file_path
        assert fig_path.is_file() and fig_path.stat().st_size > 0


def test_spawn_ocr_teardown(glm_spec):
    spec, quant = glm_spec
    manager = LlamaServerManager(
        model_path=store.quant_path(spec, quant),
        mmproj_path=store.mmproj_path(spec),
        context_size=spec.context_size,
    )
    with manager:
        manager.start()
        assert manager.state is ServerState.READY
        assert manager.is_alive()
        engine = VLMEngine(spec, manager)
        result = engine.extract_page(_test_page_image(), PageHints(page_index=0))
        assert result.markdown, "empty OCR output"
        lowered = result.markdown.lower()
        assert "quick brown fox" in lowered, f"unexpected OCR output: {result.markdown!r}"
    assert not manager.is_alive(), "llama-server left running after teardown"
    assert manager.state is ServerState.STOPPED
