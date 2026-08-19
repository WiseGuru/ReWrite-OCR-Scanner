"""Generate the application icon: packaging/icon.png (256px, used by the
AppImage and About) and packaging/icon.ico (multi-size, used by the Windows
executable and installer). Pure Pillow, deterministic; re-run after design
changes and commit the outputs."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

BG = "#1565c0"
PAGE = "#ffffff"
LINES = "#90a4ae"
BEAM = "#ffb300"


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 256.0
    # Rounded background tile.
    d.rounded_rectangle([8 * s, 8 * s, 248 * s, 248 * s], radius=44 * s, fill=BG)
    # Page.
    d.rounded_rectangle([64 * s, 40 * s, 192 * s, 216 * s], radius=10 * s, fill=PAGE)
    # Text lines.
    for i, width in enumerate((96, 96, 64, 96, 80, 48)):
        y = (64 + i * 24) * s
        d.rounded_rectangle(
            [80 * s, y, (80 + width) * s, y + 10 * s], radius=5 * s, fill=LINES
        )
    # Scan beam across the middle.
    d.rounded_rectangle([40 * s, 118 * s, 216 * s, 138 * s], radius=10 * s, fill=BEAM)
    return img


def main() -> int:
    out_dir = Path(__file__).resolve().parents[1] / "packaging"
    out_dir.mkdir(exist_ok=True)
    base = draw_icon(256)
    base.save(out_dir / "icon.png")
    base.save(
        out_dir / "icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"wrote {out_dir / 'icon.png'} and {out_dir / 'icon.ico'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
