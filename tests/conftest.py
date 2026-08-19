"""Shared fixtures: programmatic PDF factories (reportlab, dev-only dep) and
an isolated app data directory for every non-integration test."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


@pytest.fixture(autouse=True)
def _isolated_app_data(request, tmp_path, monkeypatch):
    """Point the app data dir at a temp dir so tests never touch the real
    settings, models, or profiles. Integration tests need the real model
    store, so they opt out via their marker."""
    if request.node.get_closest_marker("integration"):
        yield
        return
    monkeypatch.setenv("REWRITEOCR_DATA_DIR", str(tmp_path / "appdata"))
    yield


PAGE_W, PAGE_H = LETTER  # 612 x 792 pt


def _paragraph(c: canvas.Canvas, x: float, y: float, lines: list[str], size: int = 11):
    text = c.beginText(x, y)
    text.setFont("Helvetica", size)
    for ln in lines:
        text.textLine(ln)
    c.drawText(text)


def make_born_digital_pdf(path: Path, n_pages: int = 6) -> Path:
    """Text pages with a running header, page numbers, and a hyphenated
    word crossing the page 1 to page 2 boundary."""
    c = canvas.Canvas(str(path), pagesize=LETTER)
    for i in range(n_pages):
        # Drawing order defines the text layer's content order: running
        # header first, page number last, so the stitching heuristics can
        # see them in the first and last line slots.
        c.setFont("Helvetica", 9)
        c.drawString(72, PAGE_H - 40, "A History of Fixtures")
        body = [
            f"This is the body text of page {i + 1}. It contains several",
            "sentences of ordinary prose so that triage sees a healthy",
            "text layer with plausible words and coverage.",
        ]
        if i == 0:
            body.append("The final word of this page is hyphen-")
        if i == 1:
            # Continuation must open the page body for the rejoin heuristic.
            _paragraph(c, 72, PAGE_H - 140,
                       ["ated across the page boundary for stitching tests."])
            c.setFont("Helvetica-Bold", 16)
            c.drawString(72, PAGE_H - 180, f"Chapter {i + 1}")
            _paragraph(c, 72, PAGE_H - 220, body)
        else:
            c.setFont("Helvetica-Bold", 16)
            c.drawString(72, PAGE_H - 100, f"Chapter {i + 1}")
            _paragraph(c, 72, PAGE_H - 140, body)
        c.setFont("Helvetica", 9)
        c.drawRightString(PAGE_W - 72, 40, str(i + 1))
        c.showPage()
    c.save()
    return path


def render_text_image(lines: list[str], size: tuple[int, int] = (1275, 1650)) -> Image.Image:
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=32)
    y = 120
    for ln in lines:
        draw.text((100, y), ln, fill="black", font=font)
        y += 56
    return img


def make_scanned_pdf(path: Path, n_pages: int = 3) -> Path:
    """Image-only pages: no text layer at all."""
    c = canvas.Canvas(str(path), pagesize=LETTER)
    for i in range(n_pages):
        img = render_text_image(
            [
                f"Scanned Page {i + 1}",
                "The quick brown fox jumps over the lazy dog.",
                "Pack my box with five dozen liquor jugs.",
            ]
        )
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        c.drawImage(ImageReader(buf), 0, 0, width=PAGE_W, height=PAGE_H)
        c.showPage()
    c.save()
    return path


def make_mixed_pdf(path: Path) -> Path:
    """One page: text in the top half, a large untexted image in the bottom."""
    c = canvas.Canvas(str(path), pagesize=LETTER)
    _paragraph(
        c,
        72,
        PAGE_H - 100,
        [
            "This mixed page has a born-digital paragraph up here with",
            "enough words to pass the text sanity checks comfortably,",
            "followed by a pasted scan below with no text layer of its own.",
        ],
    )
    img = render_text_image(["Pasted scan content"], size=(1000, 900))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    c.drawImage(ImageReader(buf), 36, 36, width=PAGE_W - 72, height=PAGE_H * 0.55)
    c.showPage()
    c.save()
    return path


def make_garbage_text_pdf(path: Path) -> Path:
    """A page whose text layer is junk from a prior bad OCR pass."""
    c = canvas.Canvas(str(path), pagesize=LETTER)
    junk = ["¶¤¨ˆ˜%%%%±µ !!!! ~~~~ ;;;; ::::" * 3] * 12
    _paragraph(c, 72, PAGE_H - 100, junk)
    c.showPage()
    c.save()
    return path


@pytest.fixture
def born_digital_pdf(tmp_path):
    return make_born_digital_pdf(tmp_path / "born.pdf")


@pytest.fixture
def scanned_pdf(tmp_path):
    return make_scanned_pdf(tmp_path / "scanned.pdf")


@pytest.fixture
def mixed_pdf(tmp_path):
    return make_mixed_pdf(tmp_path / "mixed.pdf")


@pytest.fixture
def garbage_text_pdf(tmp_path):
    return make_garbage_text_pdf(tmp_path / "garbage.pdf")
