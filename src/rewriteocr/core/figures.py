"""Figure region handling: crop at native render scale and reference by
relative path. Never re-render or upscale a crop; the model and the reader
both get pixels at the scale the page render produced."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from rewriteocr.core.models import Region


def crop_region(image: Image.Image, region: Region) -> Image.Image:
    r = region.normalized()
    left = round(r.x0 * image.width)
    top = round(r.y0 * image.height)
    right = round(r.x1 * image.width)
    bottom = round(r.y1 * image.height)
    left, right = max(0, left), min(image.width, right)
    top, bottom = max(0, top), min(image.height, bottom)
    if right <= left or bottom <= top:
        raise ValueError(f"Degenerate figure region {region}")
    return image.crop((left, top, right, bottom))


def save_figure(
    image: Image.Image, region: Region, figures_dir: Path, page_index: int, seq: int
) -> str:
    """Writes the crop and returns the path relative to the figures dir's parent."""
    figures_dir.mkdir(parents=True, exist_ok=True)
    name = f"page{page_index + 1:04d}_fig{seq:02d}.png"
    out_path = figures_dir / name
    crop_region(image, region).save(out_path, format="PNG")
    return f"{figures_dir.name}/{name}"
