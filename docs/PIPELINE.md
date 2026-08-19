# Pipeline: triage, extraction, flags, stitching, export

Update this doc in the same change as any behavior it describes.
Everything here is Qt-free and unit-tested; thresholds are named constants
in their modules and pinned by fixture tests.

## Triage (`core/triage.py`)

Per page: text layer, glyph boxes, and image-object boxes from pypdfium2.

- Text-layer sanity (`text_sanity`): printable ratio >= 0.95, alphanumeric
  ratio of non-space chars >= 0.50, mean token length in 1.5-15. A present
  but garbage layer (prior bad OCR pass) fails this and the page is
  `scanned`.
- Under 25 stripped chars: `scanned` (blank pages land here harmlessly).
- Sane text with glyph-box union area >= 2% of the page: `born_digital`,
  unless image objects not covered by text exceed 30% of the page, which
  makes it `mixed`.
- Union areas are approximated on a 64x64 grid (`_union_area`); exact
  rectangle union is overkill at these thresholds.
- v1 simplification (spec-permitted): `mixed` is extracted as scanned, but
  the classification is recorded and shown.

## Preprocessing (`core/preprocess.py`)

- Deskew estimation: numpy projection-profile scoring (shear y by
  candidate angle, maximize row-histogram variance), coarse sweep of -5 to
  +5 deg at 0.5 then fine 0.1 steps; angles under 0.2 deg are stored as 0.
  Estimated once per scanned page at extraction and stored in the sidecar;
  never baked into a saved image, applied at render time
  (`apply_deskew`, white fill, no expansion, so region coordinates keep
  meaning).
- Rotation override (0/90/180/270) is applied by pdfium at render time,
  before deskew estimation.
- Rasterization at the manifest's `preprocess.dpi`, then downscaled so the
  longest edge fits `preprocess.longest_edge_px` (never upscaled).
- Deliberately nothing else: binarization/despeckle/sharpen hurt VLM
  accuracy and exist only inside Otsu-based measurement helpers
  (`ink_ratio`, skew estimation), never applied to model input.

## Extraction (`pipeline/extract.py`)

`extract_document` targets pages with NULL `extracted_text` (or an explicit
`page_indices` list for re-extraction). Per page, by classification:

- **born_digital**: no model call. With no regions, the PDF's own text
  order is used verbatim. With regions, glyphs are filtered geometrically
  (exclusion = center-point test) and text is rebuilt from glyph geometry
  (`core/rules.glyphs_to_text`). Engine id: `text_layer`.
- **scanned/mixed**: render at model DPI, estimate/store deskew, prepare
  the model image, run the primary engine (VLM if a model is installed and
  selected, else Tesseract). While the VLM runs on GPU, Tesseract runs the
  same masked page on a CPU thread for the cross-check flag.

### Region semantics on scanned pages

- `exclude` regions are painted white on the model image before OCR
  (`_mask_regions`); the VLM never sees them.
- **Explicit-layout mode** when any `column` or `heading` region exists:
  only regions are transcribed, in `order_index` order. This is the manual
  reading-order escape hatch; leftover area is intentionally ignored.
- **Carve-out mode** when only `table`/`figure` regions exist: the page is
  read normally with the carved areas masked out, then each carve-out's
  output is appended in order (figure link, or table via the manifest's
  table prompt as HTML). Drawing one figure box must not discard the rest
  of the page; the integration test pins this.
- Crops are taken at native render scale, never re-rendered or upscaled.
- Region engine auto-switch: below the model's `min_region_lines` (counted
  by Tesseract line boxes), the region routes to Tesseract instead of the
  VLM (VLMs loop on tiny fragments). Recorded in stats and reported, never
  silent.

### Failure handling

`EngineCrashedError` (server died: OOM or crash) triggers a CPU restart of
llama-server and a retry, at most `MAX_CRASH_RESTARTS=2` per run; the run
is marked `device_fallback` and the UI shows the device change. Page-level
`PdfPageDamagedError`/`EngineError` mark that page failed and the run
continues. Cancellation raises out of `JobControl.checkpoint()` between
pages; committed pages stay.

## Flags (`core/flags.py`)

Computed after each page, stored atomically with the result; severity
0.0-1.0 drives review ordering.

| Flag | Trigger | Notes |
|---|---|---|
| `repetition` | any 5-gram repeating > 4 times, or the last 400 chars form a cycle repeating >= 3 times (string-doubling period check) | the signature VLM failure; detail names the repeated phrase |
| `low_yield` | output chars < 25% of expected for the page's ink (Otsu ink ratio, ~250 ink px per char at model DPI), ignoring near-blank pages | catches extraction that died mid-page |
| `engine_disagreement` | normalized (markdown-stripped, lowercased) `difflib` similarity between VLM and Tesseract below 0.80 | only when both engines ran; both texts must be >= 40 chars |

## Cross-page stitching (`core/stitching.py`)

Export-time only, on a copy of the page list; the sidecar text is never
rewritten. Order: running headers/footers dropped (same normalized line in
the same slot on > 60% of pages; digit-only lines collapse to one page
number sentinel; needs >= 5 nonempty pages), then table continuations
merged (trailing pipe table + leading headerless pipe table with equal
column count), then hyphenated words rejoined (trailing `\w-` + lowercase
continuation). Each step logs into `StitchLog`, surfaced in the export
summary. Note: `core/pdf_io.py` restores PDFium's U+FFFE soft-hyphen marker
to `-` plus a line break so the rejoin heuristic can see it.

## Export (`pipeline/export_md.py`, `pipeline/export_docx.py`)

Markdown is canonical; DOCX renders from it (markdown-it-py token walk into
python-docx), never independently. Page-break option: none, HTML comment,
or rule (a real page break in DOCX). Pipe tables become Word tables; HTML
tables (the table-region output) go through `_HtmlTableGrid`, which
resolves rowspan/colspan into `cell.merge` calls. Figures embed inline,
with a text placeholder when the file is missing. `edited_text` always
wins over `extracted_text`.
