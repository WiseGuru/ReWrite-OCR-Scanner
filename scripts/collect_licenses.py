"""Populate src/rewriteocr/resources/licenses/ with third-party license
texts and attributions for the About dialog and the distributed bundles.

Coverage:
- Runtime Python dependencies: texts copied from their installed dist-info,
  including files under a dist-info licenses/ tree (pypdfium2 keeps the
  PDFium and PDFium-third-party notices there, and we redistribute that
  binary).
- Qt (PySide6/shiboken6): tri-licensed; this project elects LGPL-3.0-only.
  Their dist-info ships only the commercial-license stub, so these entries
  are composed here and point at the canonical LGPL-3.0.txt and GPL-3.0.txt
  kept in the same folder (LGPL-3.0 is a supplement to GPL-3.0).
- The embedded Python runtime (PSF-2.0), copied from the running
  interpreter, and the PyInstaller bootloader notice (both ship inside the
  packaged application).
- External binaries and models that are detected or downloaded but never
  redistributed by this project: pointer notices only.

Re-run after dependency changes and commit the result. LGPL-3.0.txt and
GPL-3.0.txt are canonical static texts (from gnu.org) and are not rewritten
by this script.
"""

from __future__ import annotations

import sys
from importlib import metadata
from pathlib import Path

RUNTIME_PACKAGES = [
    "pypdfium2", "pillow", "numpy",
    "python-docx", "markdown-it-py", "mdurl", "typing_extensions", "lxml",
]

QT_PACKAGES = ["PySide6", "shiboken6"]

QT_NOTICE = """\
{name} {version} (Qt for Python)

Qt and Qt for Python are available under commercial licenses or under the
GNU Lesser General Public License version 3 or the GNU General Public
License. This application uses {name} under the
**LGPL-3.0-only** option, as an unmodified library, dynamically linked:
the Qt/PySide6 shared libraries ship as separate files in the application
folder and can be replaced or relinked by the user.

Full license text: see LGPL-3.0.txt in this folder. LGPL-3.0 is a set of
additional permissions on top of GPL-3.0; see GPL-3.0.txt for the base
text. Source code: https://code.qt.io/cgit/pyside/pyside-setup.git/ and
https://download.qt.io/official_releases/qt/
"""

PSF_FALLBACK = (
    "Python (embedded runtime)\nLicense: PSF-2.0\n"
    "https://docs.python.org/3/license.html\n"
)

EXTERNAL_NOTICES = {
    "PyInstaller-bootloader": (
        "PyInstaller bootloader (embedded in the packaged executable)\n"
        "License: GPL-2.0-or-later with the PyInstaller Bootloader"
        " Exception, which explicitly permits distributing bundled"
        " applications under their own terms.\n"
        "https://pyinstaller.org/en/stable/license.html\n"
    ),
    "llama.cpp": (
        "llama.cpp (inference runtime, detected on the system; not"
        " distributed with this application)\n"
        "License: MIT\n"
        "https://github.com/ggml-org/llama.cpp/blob/master/LICENSE\n"
    ),
    "Tesseract-OCR": (
        "Tesseract OCR (optional, detected on the system; not distributed"
        " with this application)\nLicense: Apache-2.0\n"
        "https://github.com/tesseract-ocr/tesseract/blob/main/LICENSE\n"
    ),
    "GLM-OCR-model": (
        "GLM-OCR model weights (downloaded at runtime by the user, not"
        " distributed with this application)\nLicense: MIT\n"
        "https://huggingface.co/zai-org/GLM-OCR\n"
    ),
    "LightOnOCR-model": (
        "LightOnOCR model weights (downloaded at runtime by the user, not"
        " distributed with this application)\nLicense: Apache-2.0\n"
        "https://huggingface.co/lightonai/LightOnOCR-1B-1025\n"
    ),
}

SEPARATOR = "\n\n" + "=" * 70 + "\n\n"


def _dist_license_texts(dist) -> list[tuple[str, str]]:
    """(label, text) for every license-ish file the dist ships: named like a
    license, or living under a dist-info licenses/ tree."""
    out: list[tuple[str, str]] = []
    for f in dist.files or []:
        path_str = str(f).replace("\\", "/")
        name = f.name.lower()
        named_like_license = (
            "license" in name or "copying" in name or name == "notice"
        )
        in_licenses_tree = ".dist-info/licenses/" in path_str.lower()
        if not (named_like_license or in_licenses_tree):
            continue
        try:
            text = f.locate().read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        label = path_str.split(".dist-info/licenses/")[-1] if in_licenses_tree else f.name
        out.append((label, text))
    return out


def write_runtime_package(out_dir: Path, package: str) -> None:
    try:
        dist = metadata.distribution(package)
    except metadata.PackageNotFoundError:
        print(f"skip (not installed): {package}")
        return
    meta = dist.metadata
    texts = _dist_license_texts(dist)
    header = (
        f"{meta['Name']} {dist.version}\n"
        f"License: {meta.get('License-Expression') or meta.get('License') or 'see text'}\n\n"
    )
    if texts:
        body = SEPARATOR.join(f"--- {label} ---\n\n{text}" for label, text in texts)
    else:
        body = (
            "License text not shipped in the package metadata; see the"
            " project page for the full text.\n"
        )
    (out_dir / f"{meta['Name']}.txt").write_text(header + body, encoding="utf-8")
    print(f"wrote {meta['Name']}.txt ({len(texts)} file(s))")


def write_qt_package(out_dir: Path, package: str) -> None:
    try:
        version = metadata.version(package)
    except metadata.PackageNotFoundError:
        print(f"skip (not installed): {package}")
        return
    (out_dir / f"{package}.txt").write_text(
        QT_NOTICE.format(name=package, version=version), encoding="utf-8"
    )
    print(f"wrote {package}.txt (LGPL election notice)")


def write_python_runtime(out_dir: Path) -> None:
    text = PSF_FALLBACK
    for candidate in ("LICENSE.txt", "LICENSE"):
        p = Path(sys.base_prefix) / candidate
        if p.is_file():
            header = (
                f"Python {sys.version.split()[0]} (embedded runtime)\n"
                "License: PSF-2.0\n\n"
            )
            text = header + p.read_text(encoding="utf-8", errors="replace")
            break
    (out_dir / "Python.txt").write_text(text, encoding="utf-8")
    print("wrote Python.txt")


def main() -> int:
    out_dir = Path(__file__).resolve().parents[1] / "src/rewriteocr/resources/licenses"
    out_dir.mkdir(parents=True, exist_ok=True)
    for canonical in ("LGPL-3.0.txt", "GPL-3.0.txt"):
        if not (out_dir / canonical).is_file():
            print(f"WARNING: {canonical} missing; fetch it from gnu.org and commit it.")
    for package in QT_PACKAGES:
        write_qt_package(out_dir, package)
    for package in RUNTIME_PACKAGES:
        write_runtime_package(out_dir, package)
    write_python_runtime(out_dir)
    for name, notice in EXTERNAL_NOTICES.items():
        (out_dir / f"{name}.txt").write_text(notice, encoding="utf-8")
        print(f"wrote {name}.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
