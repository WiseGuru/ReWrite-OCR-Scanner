"""Preprocessing for scanned pages: deskew estimation and model rasterization.

Deskew angles are stored and applied at render time; source images are never
modified. No binarization, despeckling, or sharpening: those serve legacy OCR
engines and push pages out of a VLM's training distribution.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from rewriteocr.modelmgr.manifest import PreprocessSpec

# Angles smaller than this are treated as straight.
MIN_STORED_ANGLE_DEG = 0.2
COARSE_RANGE_DEG = 5.0
COARSE_STEP_DEG = 0.5
FINE_STEP_DEG = 0.1
# Downsample target for skew estimation; accuracy is fine at low resolution.
ESTIMATE_MAX_WIDTH = 1000


def _binarize(gray: np.ndarray) -> np.ndarray:
    """Otsu threshold; returns boolean foreground (ink) mask."""
    hist, _ = np.histogram(gray, bins=256, range=(0, 256))
    total = gray.size
    sum_all = np.dot(np.arange(256), hist)
    sum_bg, w_bg, best_t, best_var = 0.0, 0, 0, -1.0
    for t in range(256):
        w_bg += hist[t]
        if w_bg == 0:
            continue
        w_fg = total - w_bg
        if w_fg == 0:
            break
        sum_bg += t * hist[t]
        m_bg = sum_bg / w_bg
        m_fg = (sum_all - sum_bg) / w_fg
        var = w_bg * w_fg * (m_bg - m_fg) ** 2
        if var > best_var:
            best_var, best_t = var, t
    return gray <= best_t


def ink_ratio(image: Image.Image) -> float:
    gray = np.asarray(image.convert("L"), dtype=np.uint8)
    return float(_binarize(gray).mean())


def _shear_score(ys: np.ndarray, xs: np.ndarray, angle_deg: float, n_rows: int) -> float:
    """Variance of the row-projection histogram after shearing by the angle.
    Sharp peaks (aligned text lines) maximize variance."""
    sheared = ys - xs * np.tan(np.radians(angle_deg))
    hist, _ = np.histogram(sheared, bins=n_rows)
    return float(np.var(hist))


def estimate_skew(image: Image.Image) -> float:
    """Estimated skew in degrees; pass the result to apply_deskew to correct.
    Positive values mean the page content is tilted clockwise."""
    gray_img = image.convert("L")
    if gray_img.width > ESTIMATE_MAX_WIDTH:
        scale = ESTIMATE_MAX_WIDTH / gray_img.width
        gray_img = gray_img.resize(
            (ESTIMATE_MAX_WIDTH, max(1, int(gray_img.height * scale))), Image.BILINEAR
        )
    gray = np.asarray(gray_img, dtype=np.uint8)
    fg = _binarize(gray)
    ys, xs = np.nonzero(fg)
    if ys.size < 100:
        return 0.0
    ys = ys.astype(np.float64)
    xs = xs.astype(np.float64)
    n_rows = gray.shape[0]

    best_angle, best_score = 0.0, -1.0
    a = -COARSE_RANGE_DEG
    while a <= COARSE_RANGE_DEG + 1e-9:
        s = _shear_score(ys, xs, a, n_rows)
        if s > best_score:
            best_score, best_angle = s, a
        a += COARSE_STEP_DEG
    coarse = best_angle
    a = coarse - COARSE_STEP_DEG
    while a <= coarse + COARSE_STEP_DEG + 1e-9:
        s = _shear_score(ys, xs, a, n_rows)
        if s > best_score:
            best_score, best_angle = s, a
        a += FINE_STEP_DEG

    if abs(best_angle) < MIN_STORED_ANGLE_DEG:
        return 0.0
    return round(best_angle, 2)


def apply_deskew(image: Image.Image, angle_deg: float) -> Image.Image:
    """Rotate to correct the measured skew. White fill, no expansion, so
    region coordinates keep meaning across the corrected page."""
    if not angle_deg:
        return image
    return image.rotate(
        angle_deg, resample=Image.BICUBIC, expand=False, fillcolor="white"
    )


def fit_to_longest_edge(image: Image.Image, longest_edge_px: int) -> Image.Image:
    longest = max(image.width, image.height)
    if longest_edge_px <= 0 or longest <= longest_edge_px:
        return image
    scale = longest_edge_px / longest
    return image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.LANCZOS,
    )


def prepare_model_image(
    rendered: Image.Image, deskew_angle: float, spec: PreprocessSpec
) -> Image.Image:
    """Rotation override is applied at render time by pdfium; this applies
    deskew and the manifest's size limit."""
    img = apply_deskew(rendered, deskew_angle)
    return fit_to_longest_edge(img, spec.longest_edge_px)
