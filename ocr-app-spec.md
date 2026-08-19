# Project Specification: Local PDF OCR to Markdown/DOCX

**Version:** 1.0 (v1 scope)
**Target platforms:** Windows, Linux
**License posture:** All dependencies permissive (MIT/Apache/BSD/LGPL). Project license is a free choice.

---

## 1. Purpose and scope

### What this is

A desktop application that converts PDFs (born-digital, scanned, or mixed) into Markdown and DOCX using a local vision-language OCR model, with a human-in-the-loop review and correction workflow. Everything runs on the user's machine. No network access is required after model download.

### The core insight driving the design

Modern OCR is a vision-language model that reads a page image and emits Markdown directly. It is not a text-recognition engine followed by a layout heuristic. The application's value is therefore not the inference step (which is a commodity) but everything wrapped around it: page triage, region annotation, failure detection, correction, and format rendering.

### Non-goals for v1

- Android, iOS, macOS
- RTF output
- Bring-your-own-model (arbitrary GGUF or endpoint)
- Hosted/cloud OCR providers (BYOK)
- Multi-document batch queues
- Any form of telemetry or network calls beyond model download

### Success criteria

A user with a 300-page scanned book can produce clean Markdown or DOCX in one session, reviewing roughly 10 to 30 flagged pages rather than all 300, without installing a separate model runtime or knowing what an mmproj file is.

---

## 2. Technology stack

| Concern | Choice | License |
|---|---|---|
| Language | Python 3.11+ | PSF |
| UI | PySide6 (Qt 6) | LGPL-3.0 |
| PDF parse and render | pypdfium2 | BSD-3 / Apache-2.0 |
| Primary OCR model | GLM-OCR (0.9B) | MIT |
| Alternate OCR model | LightOnOCR-2-1B | Apache-2.0 |
| Layout detection | PP-DocLayout-V3 | Apache-2.0 |
| Fallback OCR / geometry oracle | Tesseract (via pytesseract or tesserocr) | Apache-2.0 |
| Inference runtime | llama.cpp (embedded, via llama-cpp-python or subprocess) | MIT |
| DOCX output | python-docx | MIT |
| Image handling | Pillow | MIT-CMU |
| Packaging | PyInstaller | GPL-2.0 with bootloader exception (does not affect output binaries) |

### Explicitly excluded dependencies and why

- **PyMuPDF**: AGPL-3.0. pypdfium2 covers rendering and text extraction. Do not add it.
- **Surya, Marker**: GPL-3.0. Not needed given the chosen stack.
- **MinerU**: AGPL-3.0.
- **DocLayout-YOLO or any Ultralytics-derived detector**: AGPL-3.0, and the obligation attaches to the weights, not just the training code. PP-DocLayout-V3 is the Apache-licensed equivalent.
- **Pandoc**: GPL-2.0+, plus a large external binary to bundle across platforms. python-docx covers the need.

### GPU backend policy

llama.cpp's **Vulkan** backend is the default GPU path. It covers NVIDIA, AMD, and Intel with one build and carries no proprietary redistribution terms.

A CUDA build may be offered as an optional separate download for users who want maximum throughput. It must never be the default, because NVIDIA's redistribution terms and installer size are both problems.

CPU is always available as a fallback and must be the automatic choice when GPU probing fails.

---

## 3. Architecture

Four layers, with a hard rule: **the UI layer never calls the inference layer directly.** All work goes through the job queue so that pause, resume, cancel, and progress reporting work uniformly.

```
┌─────────────────────────────────────────────┐
│  UI layer (PySide6)                         │
│  Import · Rules · Extract · Review · Export │
└───────────────┬─────────────────────────────┘
                │ signals/slots, no blocking calls
┌───────────────▼─────────────────────────────┐
│  Job queue (QThread workers)                │
│  Progress, pause/resume/cancel, ordering    │
└───────────────┬─────────────────────────────┘
                │
┌───────────────▼─────────────────────────────┐
│  Pipeline                                   │
│  Triage → Preprocess → Extract → Flag       │
│                          → Normalize        │
└───────────────┬─────────────────────────────┘
                │
┌───────────────▼─────────────────────────────┐
│  Engine layer                                │
│  VLMEngine (llama.cpp) · TesseractEngine     │
│  LayoutEngine (PP-DocLayout)                 │
└──────────────────────────────────────────────┘
```

### Engine interface

Even though v1 does not expose BYO models, define the engine interface generically so adding models later is a manifest change and not a refactor.

```python
class OCREngine(Protocol):
    def capabilities(self) -> Capabilities: ...
    def extract_page(self, image: Image, hints: PageHints) -> PageResult: ...
    def extract_region(self, image: Image, hints: RegionHints) -> RegionResult: ...

@dataclass
class Capabilities:
    region_conditioned: bool   # can it reliably read a crop?
    layout_detection: bool     # does it emit regions?
    bbox_output: bool          # can output text map back to page coords?
    min_region_lines: int      # below this, route to Tesseract
    output_format: Literal["markdown", "html", "json"]
```

UI features gate on `capabilities()`. When a capability is absent, the corresponding control is disabled with a tooltip naming the reason, never silently degraded.

---

## 4. Data model

### Sidecar file

**The source PDF is never modified, and nothing is written next to it.** All application state lives in a sidecar in the per-user app data directory (`projects/`), named for the PDF and keyed to its absolute path. Reopening the same file resumes the same project; a moved or renamed PDF is found again by a content-hash scan of the projects directory.

Format: SQLite. Not JSON. Rationale: 300-page documents with per-page edited text and region sets exceed comfortable JSON rewrite sizes, and SQLite gives incremental writes plus crash safety for free. A crash mid-extraction on page 240 must not lose pages 1 to 239.

File name: `<pdf-stem>-<path-key>.ocrproj` in the app data `projects/` directory (the path key is a short hash of the source's absolute path, so same-named PDFs in different folders never collide).

Schema:

```sql
CREATE TABLE project (
  id                INTEGER PRIMARY KEY CHECK (id = 1),
  source_hash       TEXT NOT NULL,       -- SHA-256 of source PDF
  source_filename   TEXT NOT NULL,
  source_page_count INTEGER NOT NULL,
  app_version       TEXT NOT NULL,
  schema_version    INTEGER NOT NULL,
  created_at        TEXT NOT NULL,
  modified_at       TEXT NOT NULL
);

CREATE TABLE pages (
  page_index     INTEGER PRIMARY KEY,     -- 0-based
  classification TEXT NOT NULL,           -- 'born_digital' | 'scanned' | 'mixed'
  deskew_angle   REAL DEFAULT 0.0,
  rotation       INTEGER DEFAULT 0,       -- 0 | 90 | 180 | 270, user override
  width_pt       REAL NOT NULL,
  height_pt      REAL NOT NULL,
  review_status  TEXT DEFAULT 'unreviewed', -- 'unreviewed'|'reviewed'|'needs_work'
  extracted_text TEXT,                    -- engine output, canonical Markdown
  edited_text    TEXT,                    -- user override; NULL = use extracted
  engine_used    TEXT,
  model_id       TEXT,
  model_revision TEXT,
  extracted_at   TEXT
);

CREATE TABLE regions (
  id           INTEGER PRIMARY KEY,
  scope        TEXT NOT NULL,     -- 'all'|'odd'|'even'|'range'|'single'
  scope_arg    TEXT,              -- e.g. '12-48' for range, '7' for single
  kind         TEXT NOT NULL,     -- 'exclude'|'table'|'figure'|'column'|'heading'
  heading_level INTEGER,          -- only when kind='heading'
  order_index  INTEGER NOT NULL,  -- explicit, user-visible ordering
  x0 REAL, y0 REAL, x1 REAL, y1 REAL,  -- normalized 0.0-1.0 of page box
  created_at   TEXT NOT NULL
);

CREATE TABLE flags (
  page_index INTEGER NOT NULL,
  kind       TEXT NOT NULL,   -- 'repetition'|'low_yield'|'engine_disagreement'
  severity   REAL NOT NULL,   -- 0.0-1.0
  detail     TEXT,
  PRIMARY KEY (page_index, kind)
);

CREATE TABLE figures (
  id         INTEGER PRIMARY KEY,
  page_index INTEGER NOT NULL,
  region_id  INTEGER,
  file_path  TEXT NOT NULL      -- relative to project dir
);
```

Notes on the schema:

- **Normalized coordinates are mandatory.** Page dimensions vary within a single PDF. Storing pixels guarantees breakage.
- `edited_text` being NULL rather than a copy of `extracted_text` means a re-extraction does not silently discard user edits; the UI must warn before overwriting a page that has edits.
- `model_id` and `model_revision` on each page are required for reproducible bug reports.
- On open, verify `source_hash`. If it does not match, warn the user that the source changed and offer to open read-only or discard the sidecar.

### Region profiles

A saved region set, independent of any document, for reusing layout rules across a document series.

Location: app data directory, `profiles/<name>.json`. Contains the `regions` rows plus a display name and description. Applying a profile inserts its regions into the current project.

### Model manifest

A JSON file shipped with the app and updatable without a release (checked against a bundled fallback copy if no updated version is present).

```json
{
  "manifest_version": 1,
  "models": [
    {
      "id": "glm-ocr-0.9b",
      "display_name": "GLM-OCR 0.9B",
      "description": "Default. Two-stage layout plus recognition. Strong on tables.",
      "license": "MIT",
      "license_url": "https://huggingface.co/zai-org/GLM-OCR",
      "repo": "zai-org/GLM-OCR",
      "revision": "<commit-sha>",
      "capabilities": {
        "region_conditioned": true,
        "layout_detection": true,
        "bbox_output": true,
        "min_region_lines": 2,
        "output_format": "markdown"
      },
      "preprocess": {
        "dpi": 200,
        "longest_edge_px": 1540,
        "pad_to_multiple": 0
      },
      "sampling": {
        "temperature": 0.2,
        "repeat_penalty": 1.15,
        "repeat_last_n": 128,
        "max_tokens": 1000
      },
      "quants": [
        {"name": "Q4_K_M", "file": "...", "sha256": "...", "size_mb": 397, "ram_mb": 1400},
        {"name": "Q8_0",   "file": "...", "sha256": "...", "size_mb": 639, "ram_mb": 1900},
        {"name": "F16",    "file": "...", "sha256": "...", "size_mb": 1200, "ram_mb": 2600}
      ],
      "mmproj": {"file": "...", "sha256": "...", "size_mb": 800, "quantizable": false}
    }
  ]
}
```

**Every value in `sampling` and `preprocess` must come from this file. None of it may be hardcoded.** Wrong sampling values are the direct cause of the model's characteristic looping failure, and wrong preprocessing silently costs accuracy in a way that is invisible during development.

---

## 5. Pipeline stages

### 5.1 Import and triage

On opening a PDF:

1. Compute SHA-256 of the file. Look for an existing sidecar with a matching hash and offer to resume.
2. Read page count and per-page dimensions via pypdfium2.
3. For each page, extract the text layer. Classify:
   - **born_digital**: text layer present, character count above a threshold relative to page area, and the extracted characters are mostly printable and non-garbage (some PDFs carry a broken text layer from a prior bad OCR pass, so check for a plausible ratio of alphabetic characters and word-like tokens).
   - **scanned**: no text layer, or a text layer that fails the sanity check.
   - **mixed**: text layer present but covering only part of the page, e.g. a born-digital page with a pasted scan.
4. Render thumbnails at low DPI for the page strip.

Triage is the largest speed win in the entire application. A 300-page born-digital PDF should complete in seconds with no model involvement.

**Mixed pages** get the text layer for the covered area and OCR for the rest. If this proves fiddly, the acceptable v1 simplification is to treat mixed as scanned and OCR the whole page, but the classification must still be recorded so the UI can show it.

### 5.2 Preprocessing

- **Deskew** (default on): estimate skew angle per scanned page. Store the angle; apply it at render time rather than baking it into a modified image. Rectangular region selection is meaningless on a skewed page, so this must run before annotation.
- **Rotation override**: per-page manual 90/180/270 for pages scanned sideways. Applied before deskew estimation.
- **Rasterization**: at the DPI and longest-edge from the active model's manifest entry.
- **No other image processing.** Binarization, despeckling, and sharpening exist to serve legacy OCR engines and actively hurt VLM accuracy by pushing pages out of the training distribution. If exposed at all, they are gated to the Tesseract path and default to off.

### 5.3 Global rules (optional)

A pre-extraction step for users who already know the document's layout. Skippable, and skipped by default.

- Region drawing on a representative page, with scope selection: all / odd / even / page range / single.
- Region kinds available here: `exclude` (headers, footers, page numbers, margin notes) and `column`.
- **Odd/even scoping is not optional.** Scanned books have mirrored recto/verso margins; a box clearing the gutter on odd pages sits inside the text block on even pages. This will be hit within minutes by the first book user.
- **Preview before commit**: render the region overlay on three sampled pages (first, middle, last of the scope) so the user sees where it lands before running 300 pages.

### 5.4 Extraction

Job queue behavior:

- Per-page progress, overall progress, estimated time remaining.
- Pause, resume, cancel. Cancel leaves completed pages intact in the sidecar.
- Results written to the sidecar incrementally, page by page. A crash must not lose completed work.

Per page:

1. If born_digital and no override, take the text layer, apply exclusion regions geometrically (filter glyphs by bounding box), and emit Markdown. No model call.
2. If scanned, render at model DPI, apply deskew and rotation, run the VLM.
3. In parallel on CPU while the GPU works, run Tesseract on the same page. Store the result for the cross-check flag. Discard it afterward unless Tesseract is the selected engine.
4. Compute flags (see 5.5).
5. Normalize output to canonical Markdown.

**Engine auto-switch**: regions under `min_region_lines` text lines route to Tesseract rather than the VLM, because VLMs loop or hallucinate context on very short fragments. The switch is shown in the UI on the affected page, not silent.

### 5.5 Flagging

Runs automatically after each page extracts. Flags drive review ordering.

| Flag | Detection | Why it matters |
|---|---|---|
| `repetition` | N-gram repeat scan on output. Trigger when any 5-gram repeats more than N times or the tail of the output is a repeating cycle. | The signature VLM failure. Cheap to detect, catastrophic if missed. |
| `low_yield` | Ratio of non-white pixel coverage to output token count falls outside an expected band. | Catches pages where extraction died or returned near-nothing on a dense page. |
| `engine_disagreement` | Character-level similarity between VLM output and the parallel Tesseract pass below a threshold. | Neither engine is ground truth, but disagreement is a strong signal one of them is wrong. |

Severity is a 0.0 to 1.0 score. The review queue sorts by max severity descending.

### 5.6 Review

The core trust-building surface. Without it, users have no reason to believe the output.

- **Split view**: page image left, extracted Markdown right, synchronized scroll.
- **Filter**: all pages / flagged only / needs work only. Default to flagged only when flags exist.
- **Sorted by severity**, not page order, when filtered.
- Flag reason shown inline with a plain-language explanation, e.g. "Output repeats the same phrase 40 times, which usually means extraction failed."
- **Direct text editing** in the right pane, saved to `edited_text`.
- Mark reviewed / needs work.
- Keyboard navigation: next flagged page, previous, mark reviewed and advance. This is where users spend their time, so it must be fast.
- If the active model supports `bbox_output`, highlight the corresponding page region on hover over a text block. If it does not, this feature is absent, not faked.

### 5.7 Annotation and re-extraction

Same canvas as global rules, but page-scoped and reached from a review failure.

Region kinds:

| Kind | Effect |
|---|---|
| `exclude` | Region omitted from output. |
| `table` | Extracted separately, rendered as an HTML table rather than a Markdown pipe table. |
| `figure` | Not transcribed. Cropped and saved as an image file, referenced in the output. |
| `column` | Defines reading order explicitly. Multiple column regions are processed in `order_index` sequence. |
| `heading` | Forces a heading level regardless of what the model inferred. |

Behavior rules:

- **Crop at native render scale.** Do not re-render or upscale the crop. The model expects body text at the pixel size produced by a full-page render at its specified DPI. Upscaling a paragraph to full-page dimensions puts it far outside the training distribution and degrades accuracy.
- **Snap region edges outward to text-line boundaries** detected by Tesseract. A crop that cuts mid-sentence causes the VLM to invent a completion. Tesseract is used here purely as a geometry oracle, which is what it is genuinely good at.
- **Explicit visible ordering.** Regions are numbered on the canvas. Do not infer order from geometry; it will be wrong often enough to be worse than useless, and when it is wrong the user cannot see why.
- **Re-extract selected pages only.** Never the whole document.
- If a page has `edited_text`, warn before re-extraction overwrites it.

`column` is the quiet workhorse here. It is the manual escape hatch for the failure users complain about most (garbled reading order on unusual layouts), and it is more reliable than any model's inferred order.

### 5.8 Output

**Markdown is the canonical intermediate.** DOCX renders from it. There is no independent DOCX generation path.

Markdown output:
- Standard CommonMark plus HTML tables where complexity requires it.
- Figures written to `<output-stem>_figures/` and referenced relatively.
- Optional page-break markers (configurable: none, HTML comment, horizontal rule).
- Pages with `edited_text` use the edit; otherwise `extracted_text`.

DOCX output via python-docx:
- Headings map to Word heading styles.
- Markdown tables map to Word tables. HTML tables with merged cells map to merged Word cells.
- Figures embedded inline.
- Page breaks preserved if the option is set.

Cross-page stitching, applied at export time:
- Rejoin words hyphenated across a page break.
- Detect and drop repeated headers and footers that survived region exclusion (a string appearing at the same position on more than 60% of pages is almost certainly a running header).
- Merge tables that continue across a page boundary when the continuation has no header row and matching column count.

---

## 6. Model management

- **Weights are never bundled in the installer.** Downloaded at runtime from Hugging Face. This keeps the project out of the redistributor role and lets license acknowledgment land with the user.
- **Pinned by commit SHA**, never by tag or branch. HF repos are updated in place; two users installing months apart must get identical weights or bug reports become unreproducible.
- **mmproj downloads automatically with the decoder and is never quantized.** Quantizing the vision encoder significantly degrades image understanding. Do not expose this as a user option.
- Download UI: resume on interruption, SHA-256 verification, free disk space precheck before starting, clear size and RAM figures per quant.
- License text shown once per model with an explicit acknowledgment before first use.
- Model picker shows quant options with a plain-language quality/size tradeoff, not raw quant names alone.
- The app must run with no model installed, doing born-digital extraction and Tesseract only, and prompt for download when a scanned page needs the VLM.

---

## 7. UI structure

Single main window, five-step wizard-style tab bar that also permits free navigation once a project is open.

```
[ Import ] [ Rules ] [ Extract ] [ Review ] [ Export ]
```

Persistent left panel: page thumbnail strip with per-page badges for classification (born-digital / scanned), flag severity, and review status.

**Import**: file picker, triage summary ("287 pages: 12 scanned, 275 with text layer"), model status.

**Rules**: region canvas on a representative page, scope selector, three-page preview.

**Extract**: queue progress, pause/resume/cancel, engine and device in use, live per-page results appearing in the thumbnail strip.

**Review**: split view, filter and sort controls, keyboard-driven navigation.

**Export**: format selection, options (page breaks, figure handling, table style), output path, summary of unreviewed flagged pages with a confirmation if any remain.

### Annotation canvas

`QGraphicsView` with a `QGraphicsPixmapItem` for the page and `QGraphicsRectItem` subclasses for regions. Zoom, pan, draw, resize, delete, reorder. This is the hardest UI component in the application; budget accordingly.

---

## 8. Error handling and failure modes

Each of these will occur in normal use and needs a designed response, not a traceback.

| Failure | Response |
|---|---|
| GPU backend fails to initialize or produces garbage | Probe on startup with a tiny known-input inference. On failure, fall back to CPU and show a one-time notice naming the device. Never crash. |
| Out of VRAM mid-run | Catch, drop to CPU for the remaining pages, flag the run, continue. |
| Model output loops | Caught by the repetition flag. Offer a one-click retry at a higher repeat penalty on that page. |
| Encrypted or password-protected PDF | Prompt for the password. If unsupported encryption, say so plainly rather than failing silently. |
| Corrupt or partially damaged PDF | Extract what is readable, list unreadable pages explicitly. |
| Source PDF changed after project creation | Hash mismatch on open. Warn, offer read-only or discard. |
| Disk full during extraction | Precheck before starting; catch mid-run, pause the queue, prompt. |
| Crash during a long run | SQLite incremental writes mean completed pages survive. On restart, offer to resume from the last completed page. |
| Extremely large page counts | Do not hold all rendered page images in memory. Render on demand, cache with a bounded LRU. |

**Bug report affordance**: a "copy diagnostic info" button that emits app version, OS, GPU backend, model ID, model revision SHA, quant name, and the flag state of the affected page. Without the model revision, remote debugging of quality complaints is guesswork.

---

## 9. Licensing compliance checklist

- [ ] No AGPL or GPL dependency in the tree. Verify with a license scan in CI, not by eye.
- [ ] PySide6 used as an unmodified shared library (LGPL dynamic linking). Do not statically link Qt.
- [ ] Third-party license texts bundled and reachable from an About dialog.
- [ ] Model weights not included in any distributed artifact.
- [ ] Model licenses displayed and acknowledged before first use of each model.
- [ ] Tesseract language data downloaded rather than bundled, or bundled with its Apache-2.0 notice.
- [ ] If a CUDA build is offered, NVIDIA redistribution terms reviewed for that artifact specifically.

---

## 10. Build and packaging

- PyInstaller one-folder builds for Windows (`.exe` plus installer) and Linux (AppImage preferred; a Flatpak is a reasonable addition).
- llama.cpp shipped as a prebuilt shared library per platform with the Vulkan backend compiled in.
- Tesseract bundled as a binary, or detected on PATH with a bundled fallback.
- Optional separate CUDA-enabled build artifact.
- CI: build matrix for both platforms, license scan, and a smoke test that opens a fixture PDF of each classification type and completes extraction with a small model.

**Budget a full week for packaging.** PyInstaller with Qt plus native extensions plus a bundled inference library is genuinely fiddly, and it always takes longer than expected.

---

## 11. Build order

Sequenced so each phase produces something runnable and testable.

**Phase 1: the spine.** Import, triage, born-digital extraction, Markdown output, sidecar persistence. No model. This alone already handles a large fraction of real PDFs and validates the data model.

**Phase 2: inference.** Model manifest, downloader, llama.cpp integration, VLM extraction on scanned pages, DOCX output. The app is now useful.

**Phase 3: trust.** Flagging, review split view, text editing, page-level re-extraction. The app is now believable.

**Phase 4: control.** Annotation canvas, region kinds, global rules, scoping, region profiles, cross-page stitching. The app is now complete.

**Phase 5: ship.** Packaging, installers, CI, documentation.

---

## 12. Documented expectations

To be stated plainly in the README, because setting them prevents most bug reports:

- Handwriting recognition is weak across all supported models. This is a printed-document tool.
- Language coverage skews toward Latin-script and European languages. CJK, Arabic, and Indic scripts should be verified per document before relying on results. Tesseract's language packs cover the long tail at lower structural fidelity.
- Complex tables (merged cells, nested headers, multi-page continuation) degrade. The annotation step exists specifically for these cases.
- Output should be reviewed before use in any context where errors are costly. The flagging system reduces review effort; it does not eliminate the need for review.

---

## 13. Deferred to a later version

Recorded so the architecture leaves room without building for it now:

- Bring-your-own GGUF and OpenAI-compatible endpoint support (the `Capabilities` interface and JSON manifest already accommodate this)
- Hosted OCR providers with BYOK, including OS credential storage and per-conversion egress consent
- Android companion for capture and send
- macOS (Homebrew formula path, to avoid Gatekeeper notarization costs)
- Multi-document batch processing
- Auto-proposed regions from PP-DocLayout output, with user correction rather than from-scratch drawing
