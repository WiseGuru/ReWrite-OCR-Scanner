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

`drop_running_headers` and `stitch_pages` take an optional `protect`
pattern naming lines that must never be deleted however often they repeat.
Screenplay export passes `SCENE_PREFIX_RE`: a bottle episode can open more
than 60% of its pages with the same scene heading, and deleting those is
total data loss. Default `None` leaves prose behavior unchanged.

## Export format registry (`pipeline/formats.py`)

One `ExportFormatSpec` row per format carrying `key`, `label`, `suffix`,
`file_filter`, `screenplay` and `exporter`. `ExportJob` and the export tab
both read it, so a format is added in one place. Exporters share the
signature `(sidecar, pdf_path, out_path, options) -> StitchLog`; prose
exporters ignore `pdf_path` and are adapted onto it by `_prose`.
`formats_for_mode` hides the screenplay formats unless the project's
`document_mode` is `screenplay`.

## Prose export (`pipeline/export_md.py`, `pipeline/export_docx.py`)

Markdown is canonical; DOCX renders from it (markdown-it-py token walk into
python-docx), never independently. Page-break option: none, HTML comment,
or rule (a real page break in DOCX). Pipe tables become Word tables; HTML
tables (the table-region output) go through `_HtmlTableGrid`, which
resolves rowspan/colspan into `cell.merge` calls. Figures embed inline,
with a text placeholder when the file is missing. `edited_text` always
wins over `extracted_text`.

## Screenplay classification (`core/screenplay.py`)

Fountain, FDX and styled DOCX need to know that one block is a Character
cue and the next is Dialogue. Nothing upstream records that, so
`parse_screenplay(pages, indents=None)` recovers it from the stitched page
Markdown into an element stream (`Element`, `TitlePage`, `ClassifyReport`,
`Screenplay` in `core/models.py`). The stream is built per export and never
stored.

Preprocessing per line: Markdown decoration is stripped (`##` headings,
bullets, paired emphasis) because the VLM writes scene headings as
`## INT. KITCHEN - DAY` and cues as `**JOHN**`. Page furniture is then
removed and recorded in `ClassifyReport.dropped_artifacts`: whole-line
`(MORE)`, `CONTINUED:`, `CONTINUED: (n)`, bare page numbers, a
title-plus-number running header, Markdown rules, and the app's own
`<!-- page break -->` marker leaking back in on a re-export. `JOHN
(CONT'D)` attached to a cue is not furniture; the patterns are whole-line
anchored.

Decision order, first match wins:

| # | Rule | Test |
|---|---|---|
| 1 | blank line | closes the open block |
| 2 | Fountain forcing character | `@ ! . > ~`, so re-importing our own output is idempotent |
| 3 | scene heading | `SCENE_PREFIX_RE`, upper-ratio >= 0.90, <= 90 chars |
| 4 | transition | upper-ratio >= 0.90, <= 40 chars, <= 4 words, ends `TO:` or a known phrase |
| 5 | parenthetical | wrapped in parentheses **and** the previous element was a cue or dialogue |
| 6 | character cue | see below |
| 7 | dialogue | previous element was cue/parenthetical/dialogue and no blank line intervened |
| 8 | action | everything else |

Rule 6 is the whole answer to "uppercase action versus character cue", and
requires all of: a blank line before (or a page start, or an unblanked
page); text on the immediately following line; upper-ratio >= 0.90 on the
name after the caret and `(V.O.)`-style extension are split off; <= 40
chars and <= 5 words; no scene prefix; no terminal `. ! ? :` outside a
`JR./DR./MR.` whitelist. `THE DOOR EXPLODES INWARD.` fails on terminal
punctuation, `HE SLAMS THE DOOR AND RUNS FOR THE STAIRS` on word count,
`SUPER: THREE YEARS EARLIER` on the colon. A cue over 3 words or containing
a comma is emitted at confidence 0.6 and listed in
`ClassifyReport.low_confidence`.

Two decisions that look like bugs and are not: **`FADE IN:` is Action**, as
a real Final Draft export emits it and Fountain's auto-detect only fires on
lines ending in `TO:`; and **`>` is a Fountain transition only when the rest
is uppercase**, otherwise it is a Markdown blockquote and the marker is
just stripped. Thresholds are named constants at the top of the module.

### Stage plays

A stage play in the Dramatists Play Service form does not use a cue column
at all: the cue is inline, `KEN. I am not scared.`, and OCR routinely runs a
whole exchange into one paragraph. That is a different shape from a
screenplay and is handled before anything else looks at a line.

Two passes, because a mid-line cue cannot be detected safely on its own
(`...worked at the FBI. Then we left` would split on `FBI`):

1. **Learn the cast.** Names that open a line as `NAME.` or `NAME:` at least
   `MIN_STAGE_CUE_APPEARANCES` (2) times, uppercase and <= 4 words. Opening
   a line is high-confidence.
2. **Split.** Only confirmed cast names are split on mid-line. Below
   `MIN_STAGE_CAST` (2) distinct names, nothing happens and the document is
   treated as a screenplay.

Each speech becomes a `character` element plus a `dialogue` element; a stage
direction opening a speech becomes a `parenthetical`, and one that is the
whole speech becomes `action`. `ClassifyReport.stage_play` and
`ClassifyReport.cast` record what happened.

`ACT_SCENE_RE` also promotes `ACT ONE`, `Scene 3`, `PROLOGUE`, `EPILOGUE`,
`INTERMISSION` and `CURTAIN` to scene headings, where a screenplay would
have a slug line. It is anchored to a number or a spelled-out ordinal so a
line of action opening with `ACT` cannot match.

Verified against two real OCR'd plays in the project store: both were
classified entirely as `action` before this pass and correctly afterwards
(294 and 190 speeches).

### Joining

Wrapped lines join: consecutive action or dialogue lines become one
element, because screenplay text is hard-wrapped at the format's column
width and one element per printed line reflows disastrously in Final Draft.
Joining stops at a blank line and at a page boundary, except that a speech
split across a page break is rejoined, since an orphaned dialogue tail
reads as action to a Fountain parser.

Upper-ratio is 0.90 rather than an equality test against `str.upper()`
because OCR turns `I` into `l` and `O` into `0` inside cues.

A title page is pulled off page 0 before classification (its lines are
consecutive and would otherwise join into one action block) when the page
has under 12 elements and at least one `key: value` line matching Fountain's
standard keys. A bare title page with no key markers is left alone.

**Dual dialogue is not detected.** Without geometry, side-by-side dialogue
is indistinguishable from two sequential speeches; a literal `^` is
honored. Detection by x-range overlap is FR-4.

## Screenplay geometry (`core/screenplay_geom.py`)

Column position is a screenplay's strongest signal, and it exists as glyph
geometry on born-digital pages. `line_indents(sidecar, pdf_path, pages)`
re-derives it at export time from the unmodified source PDF, so nothing is
stored and no schema or engine contract changes.

Per page it returns `None` unless the page is `born_digital`, `edited_text`
is NULL (a user edit invalidates the mapping) and the PDF opens. Glyphs are
binned into lines by `rules.bin_glyph_lines` (shared with `glyphs_to_text`),
each line's indent is `min(x0) * width_pt / 72`, and the glyph lines are
aligned onto the canonical text lines with `difflib.SequenceMatcher` over a
punctuation-stripped key. Below `MIN_MATCH_RATIO = 0.5` matched lines the
page falls back to lexical. Any failure is logged and skipped; geometry
never fails an export.

The classifier measures offsets from the **document's own action margin**
(the 10th-percentile indent, so one stray glyph cannot define it), not as
absolute inches, so a script printed or scanned off-centre still
classifies. `COLUMN_OFFSETS` holds the roles: action +0.0, dialogue +1.0,
parenthetical +1.5, character +2.2, transition +4.0 inches. Geometry
overrides rules 5 to 7 but never 3 or 4, which are lexically certain.

Scanned pages get nothing: the VLM returns free-form Markdown, declares
`bbox_output: false`, and its text was never aligned to Tesseract's line
boxes. That is FR-4.

One consequence worth knowing: PDFium's raw text order emits **no blank
lines**, so every born-digital page arrives unblanked and rule 6's
blank-line requirement carries no information there. The classifier detects
that case and relaxes it, and uses "the previous dialogue line ended a
sentence" as the only available speech boundary. Those pages are exactly
the ones where geometry is available, which is why it is worth having.

## Screenplay export (`pipeline/export_screenplay.py`)

All three are additional renderers over the same canonical Markdown, so
there is still one stored representation and no path that bypasses it.
`load_screenplay` stitches (with `protect`), runs the indent oracle,
classifies, and hangs the `ClassifyReport` on `StitchLog.screenplay` so the
export result stays a plain `(out_path, StitchLog)` tuple.

**Fountain** uses the forcing characters throughout (`.` scene heading, `!`
action, `@` character plus `^` for dual, `>` transition) rather than relying
on Fountain's own inference, which misfires on uppercase action. Blank line
between elements except inside a speech; `===` between pages when the
page-break option is set. `_defuse` neutralizes `[[`, `]]`, `/*` and `*/`
in body text, since a stray `[[` would open a note and swallow the rest.
The deliberate cost: centered text and lyrics are never auto-detected.

**FDX** emits `<FinalDraft DocumentType="Script" Template="No" Version="3">`
wrapping `<Content>` with `<Paragraph Type="...">` and a directly nested
`<Text>`, via stdlib `xml.etree.ElementTree`; the declaration is written by
hand because ElementTree cannot emit `standalone="no"`.

Dual dialogue is an **untyped wrapper** `<Paragraph>` holding a
`<DualDialogue>` whose children are a flat sequence of both speakers, left
column first:

```xml
<Paragraph>                       <!-- no Type, no Text of its own -->
  <DualDialogue>
    <Paragraph Type="Character"><Text>MARA</Text></Paragraph>
    <Paragraph Type="Dialogue"><Text>I am not doing this again.</Text></Paragraph>
    <Paragraph Type="Character"><Text>DELL</Text></Paragraph>
    <Paragraph Type="Dialogue"><Text>You already did.</Text></Paragraph>
  </DualDialogue>
</Paragraph>
```

`dual_groups` pairs a completed speech with the following cue when that cue
carries `dual`, which is where Fountain puts the caret. A caret with no
speech before it, or either half missing its dialogue, degrades to two
ordinary speeches rather than emitting a wrapper Final Draft would reject.
If a reader is ever written: the wrapper has no `Type`, so `.//Paragraph`
double-counts it and iterating `Content`'s children yields a typeless
paragraph. Test for a `DualDialogue` child before reading `Type`. Evidence
and provenance are in [closed/fr-5.md](closed/fr-5.md).

Two omissions remain, both shapes no verified export was available for:
`<TitlePage>` (title fields become leading `General` paragraphs, which open
correctly) and forced page breaks (`page_break` is ignored; Final Draft
repaginates on open).

There is **no official FDX XSD or DTD**, so nothing can validate an FDX
strictly. `tests/fdxcheck.py` is a vendored structural checker that every
emitted shape is run through in `tests/test_export_fdx.py`, alongside a
reference file in `tests/data/fdx/`. It catches what hand-written assertions
miss: a Character followed by the wrong element, a malformed dual block, an
untyped paragraph with no payload. One test deliberately feeds it a
flattened wrapper to prove a green run means something.

**Styled DOCX** builds named paragraph styles programmatically from
`STYLE_SPECS`, rather than from a bundled template binary that no diff can
review. Courier New 12pt on `Normal` with the `w:eastAsia` fix, US Letter
with a 1.5in left and 1.0in right margin, and indents relative to that
margin: dialogue 1.0/1.5, parenthetical 1.5/2.0, character 2.0, transition
4.0. `keep_with_next` on headings, cues and parentheticals lets Word
paginate; `page_break` is ignored for the same reason as FDX. The prose
`DocxRenderer` is untouched.
