"""Populate src/rewriteocr/resources/licenses/ with third-party license
texts for the About dialog: runtime Python dependencies (copied from their
installed dist-info) plus external binaries and models (pointers with the
canonical license names and URLs)."""

from __future__ import annotations

import sys
from importlib import metadata
from pathlib import Path

RUNTIME_PACKAGES = [
    "PySide6", "shiboken6", "pypdfium2", "pillow", "numpy",
    "python-docx", "markdown-it-py", "mdurl", "typing_extensions", "lxml",
]

EXTERNAL_NOTICES = {
    "llama.cpp": (
        "llama.cpp (bundled or detected inference runtime)\n"
        "License: MIT\n"
        "https://github.com/ggml-org/llama.cpp/blob/master/LICENSE\n"
    ),
    "Tesseract-OCR": (
        "Tesseract OCR (optional, detected on the system)\n"
        "License: Apache-2.0\n"
        "https://github.com/tesseract-ocr/tesseract/blob/main/LICENSE\n"
    ),
    "GLM-OCR-model": (
        "GLM-OCR model weights (downloaded at runtime, not distributed"
        " with this application)\nLicense: MIT\n"
        "https://huggingface.co/zai-org/GLM-OCR\n"
    ),
    "LightOnOCR-model": (
        "LightOnOCR model weights (downloaded at runtime, not distributed"
        " with this application)\nLicense: Apache-2.0\n"
        "https://huggingface.co/lightonai/LightOnOCR-1B-1025\n"
    ),
}


def main() -> int:
    out_dir = Path(__file__).resolve().parents[1] / "src/rewriteocr/resources/licenses"
    out_dir.mkdir(parents=True, exist_ok=True)
    for package in RUNTIME_PACKAGES:
        try:
            dist = metadata.distribution(package)
        except metadata.PackageNotFoundError:
            print(f"skip (not installed): {package}")
            continue
        texts = []
        for f in dist.files or []:
            name = f.name.lower()
            if "license" in name or "copying" in name or name == "notice":
                try:
                    texts.append(f.locate().read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    continue
        meta = dist.metadata
        header = (
            f"{meta['Name']} {dist.version}\n"
            f"License: {meta.get('License-Expression') or meta.get('License') or 'see text'}\n\n"
        )
        body = ("\n\n" + "=" * 70 + "\n\n").join(texts) if texts else (
            "License text not shipped in the package metadata; see the"
            " project page for the full text.\n"
        )
        (out_dir / f"{meta['Name']}.txt").write_text(header + body, encoding="utf-8")
        print(f"wrote {meta['Name']}.txt ({len(texts)} file(s))")
    for name, notice in EXTERNAL_NOTICES.items():
        (out_dir / f"{name}.txt").write_text(notice, encoding="utf-8")
        print(f"wrote {name}.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
