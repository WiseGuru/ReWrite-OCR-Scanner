# ReWrite-OCR-Scanner

Desktop PDF OCR app (PySide6 + pypdfium2 + llama.cpp VLM): converts PDFs to
Markdown/DOCX locally with a review workflow. The design source of truth is
[ocr-app-spec.md](ocr-app-spec.md); [README.md](README.md) is the user-facing
overview; user documentation lives in [wiki/](wiki/).

## Commands

- Tests: `pytest -q` (fast, no model). Real-model integration:
  `pytest -m integration` (needs llama-server on PATH and GLM-OCR Q8_0 in
  the app model dir).
- Lint: `ruff check src tests scripts`. Gates:
  `python scripts/check_dashes.py`, `python scripts/check_licenses.py`.
- Run: `rewrite-ocr` (or `python -m rewriteocr.app`).
- Local package build: `pyinstaller --noconfirm packaging/rewriteocr.spec`.
- After dependency changes: `python scripts/collect_licenses.py`.

## Hard rules

- UI never calls engines or the pipeline directly; everything goes through
  the job queue. `core/`, `pipeline/`, `engines/` stay free of Qt imports.
- The source PDF is never modified and nothing is written next to it; all
  state lives under the app data dir (sidecar: one SQLite connection per
  thread, one transaction per page).
- Every sampling/preprocess value comes from
  `src/rewriteocr/resources/manifest.json` (pinned revisions + SHA-256).
  Never hardcode them; mmproj is never quantized by us.
- No AGPL/GPL dependencies (no PyMuPDF, Surya, Marker, MinerU, Ultralytics,
  Pandoc). CI enforces via `scripts/check_licenses.py`.
- All pdfium calls go through the global lock in `core/pdf_io.py` (PDFium
  is not thread-safe, even across documents).
- The embedded llama-server probe-binds upward from port **18131**; 18099
  and 18110 belong to other local pipelines, never use them here.

## Subsystems (deep docs in docs/)

- **Data and storage**: app-data layout, sidecar schema/invariants, project
  naming, legacy migration, figures, profiles. See
  [docs/DATA-MODEL.md](docs/DATA-MODEL.md).
- **Pipeline**: triage thresholds, deskew, extraction dispatch, region
  semantics (explicit-layout vs carve-out), flag formulas, stitching,
  exporters. See [docs/PIPELINE.md](docs/PIPELINE.md).
- **Engines and models**: llama-server lifecycle (ports, identity check,
  CPU fallback, teardown), VLM/Tesseract roles, manifest contract,
  downloader. See [docs/ENGINES.md](docs/ENGINES.md).
- **UI and jobs**: threading model, job/reporter signal flow, tabs, review
  behaviors, annotation canvas. See [docs/UI-JOBS.md](docs/UI-JOBS.md).
- **Releases**: prerelease-first tag-driven flow, asset names, version
  owner (`src/rewriteocr/__init__.py`). See [RELEASING.md](RELEASING.md).

## Documentation maintenance

Update docs in the same change as the behavior they describe, and
reorganize rather than append. The in-sync set is declared in
`.docs-sync.json` (code surface to required doc); user-facing pages are
`README.md` and `wiki/`, contributor detail lives in `docs/`. This file is
a map: when a section here outgrows a summary, move the body to its deep
doc and leave the pointer.
