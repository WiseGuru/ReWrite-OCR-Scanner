# ReWrite OCR Scanner

A desktop application that converts PDFs (born-digital, scanned, or mixed)
into Markdown and DOCX using a local vision-language OCR model, with a
human-in-the-loop review and correction workflow. Everything runs on your
machine; no network access is needed after the one-time model download.

The design spec lives in [ocr-app-spec.md](ocr-app-spec.md).

## How it works

1. **Import**: open a PDF. Pages are classified as born-digital (usable text
   layer), scanned, or mixed. Born-digital pages never touch a model, so a
   300-page digital PDF finishes in seconds.
2. **Rules** (optional): draw exclude boxes over headers, footers, and margin
   notes, or column boxes to fix reading order, scoped to all, odd, even, a
   range, or a single page. Odd/even scoping handles mirrored book margins.
   Preview shows where boxes land on three sampled pages before you commit.
3. **Extract**: scanned pages are read by GLM-OCR (default) or LightOnOCR
   through an embedded llama.cpp server, with Tesseract running a parallel
   cross-check on the CPU. Progress, pause, resume, and cancel are always
   available; completed pages are saved incrementally, so a crash or cancel
   never loses finished work.
4. **Review**: pages that look wrong are flagged (looping output, suspiciously
   low yield, engine disagreement) and sorted by severity, so a 300-page book
   typically needs 10 to 30 pages of review, not 300. Split view shows the
   page image beside editable Markdown. Keyboard: N/P to move, Ctrl+Enter to
   mark reviewed and advance, Ctrl+D for needs work. From a failed page you
   can annotate regions (exclude, table, figure, column, heading) and
   re-extract just that page.
5. **Export**: Markdown (canonical) or DOCX rendered from it. Cross-page
   cleanup rejoins hyphenated words, drops running headers and page numbers,
   and merges tables that continue across pages. Figures are cropped to real
   image files and referenced.

## Install

Grab the latest build from the
[releases page](https://github.com/WiseGuru/ReWrite-OCR-Scanner/releases).
The full walkthrough, including Linux glibc and FUSE notes, is in the
[install guide](wiki/Installation.md).

**Windows**: run `ReWrite-OCR-Scanner-Setup-<version>.exe`, or unzip the
portable `-windows-x64.zip` anywhere and run `rewrite-ocr.exe`.

**Linux**: download the `.AppImage`, `chmod +x` it, and run it (a portable
`-linux-x64.tar.gz` is also published). x86_64 only, and it needs a
reasonably current distribution; see the install guide.

**The local OCR runtime** (both platforms):

- [llama.cpp](https://github.com/ggml-org/llama.cpp) with `llama-server` on
  PATH (for example `winget install ggml.llamacpp`). The Vulkan build covers
  NVIDIA, AMD, and Intel GPUs; CPU is the automatic fallback.
- [Tesseract](https://github.com/tesseract-ocr/tesseract) (optional but
  recommended: enables the cross-check flag, region edge snapping, and a
  no-model fallback engine). On Windows:
  `winget install UB-Mannheim.TesseractOCR`.

Model weights are downloaded on first use from Hugging Face, pinned to exact
revisions and verified by SHA-256. The app runs without any model installed:
born-digital extraction and Tesseract still work, and it prompts for a
download when a scanned page needs the vision model.

## Development install

Needs Python 3.11+ on Windows or Linux:

```
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"   # Windows
.venv/bin/pip install -e ".[dev]"       # Linux
rewrite-ocr
```

Run tests with `pytest` (fast, no model needed). Integration tests that
spawn a real llama-server with downloaded weights run with
`pytest -m integration`.

## What to expect

- Handwriting recognition is weak across all supported models. This is a
  printed-document tool.
- Language coverage skews toward Latin-script and European languages. Verify
  CJK, Arabic, and Indic scripts per document before relying on results.
  Tesseract's language packs cover the long tail at lower structural
  fidelity.
- Complex tables (merged cells, nested headers, multi-page continuation)
  degrade. The annotation step exists specifically for these cases: draw a
  table region and it is re-read as an HTML table.
- Review output before use anywhere errors are costly. Flagging reduces
  review effort; it does not eliminate the need for review.

## Data and licensing

- The source PDF is never modified, and nothing is written next to it. All
  state lives in a `.ocrproj` SQLite project file under the per-user app
  data directory (`%LOCALAPPDATA%\ReWriteOCR` on Windows,
  `~/.local/share/ReWriteOCR` on Linux). Reopening the same PDF resumes its
  project, even if the PDF was moved or renamed.
- All dependencies are permissively licensed (MIT/BSD/Apache/LGPL); CI
  enforces this with a license gate. Qt is used through PySide6 under the
  LGPL as an unmodified, dynamically linked library. Model licenses (GLM-OCR:
  MIT; LightOnOCR: Apache-2.0) are shown in-app and acknowledged before first
  use; weights are never redistributed by this project.
- Third-party license texts are bundled and reachable from Help > About.

## Documentation

- User guide: [wiki/](wiki/) (installation, workflow, regions, models,
  troubleshooting).
- Contributor docs: [docs/](docs/) (data model, pipeline internals,
  engines, UI/jobs), indexed from [CLAUDE.md](CLAUDE.md).
- Releasing: [RELEASING.md](RELEASING.md) (prerelease-first, tag-driven,
  attested assets).

## Project layout

- `src/rewriteocr/core/`: Qt-free logic (PDF access, sidecar, triage,
  preprocessing, flags, stitching), fully unit-tested.
- `src/rewriteocr/engines/`: llama-server lifecycle, VLM engine, Tesseract
  engine, layout-engine interface.
- `src/rewriteocr/modelmgr/`: pinned model manifest, resumable verified
  downloads, license acknowledgments.
- `src/rewriteocr/pipeline/`: extraction orchestration and exporters.
- `src/rewriteocr/jobs/` and `src/rewriteocr/ui/`: job queue and PySide6 UI.
- `scripts/`: CI gates (license, dash style), license-text collection,
  icon generation, AppImage build.
- `packaging/`: PyInstaller spec, Windows installer script, app icon.
