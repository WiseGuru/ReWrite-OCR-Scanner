import pytest
from PIL import Image, ImageDraw

from rewriteocr.core.preprocess import (
    apply_deskew,
    estimate_skew,
    fit_to_longest_edge,
    ink_ratio,
)


def _lined_page(size=(800, 1000)) -> Image.Image:
    """Synthetic text-like page: many horizontal dark bars."""
    img = Image.new("L", size, 255)
    draw = ImageDraw.Draw(img)
    for y in range(100, size[1] - 100, 40):
        draw.rectangle([80, y, size[0] - 80, y + 12], fill=0)
    return img


@pytest.mark.parametrize("true_skew", [-3.0, -1.5, 1.0, 2.5])
def test_estimate_skew_recovers_known_tilt(true_skew):
    page = _lined_page()
    # Tilt the page content by -true_skew so that estimate should report
    # +true_skew as the correction to apply.
    tilted = page.rotate(-true_skew, resample=Image.BICUBIC, expand=False, fillcolor=255)
    est = estimate_skew(tilted)
    assert abs(est - true_skew) <= 0.3, (true_skew, est)
    corrected = apply_deskew(tilted.convert("RGB"), est)
    assert abs(estimate_skew(corrected)) <= 0.3


def test_estimate_skew_straight_page_is_zero():
    assert estimate_skew(_lined_page()) == 0.0


def test_estimate_skew_blank_page_is_zero():
    assert estimate_skew(Image.new("L", (500, 500), 255)) == 0.0


def test_fit_to_longest_edge_downscales_only():
    big = Image.new("RGB", (3000, 2000), "white")
    small = Image.new("RGB", (800, 600), "white")
    fitted = fit_to_longest_edge(big, 1540)
    assert max(fitted.size) == 1540
    assert fitted.height / fitted.width == pytest.approx(2000 / 3000, abs=0.01)
    assert fit_to_longest_edge(small, 1540).size == (800, 600)


def test_ink_ratio_scales_with_coverage():
    page = _lined_page()
    blank = Image.new("L", (800, 1000), 255)
    assert ink_ratio(page) > 0.05
    assert ink_ratio(page) > ink_ratio(blank)
