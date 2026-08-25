# Roadmap: feature, triage and security items

Standing register of **requested but unbuilt** work, with the date each item
was requested and the version it shipped in. It is the durable record of
*what was asked for and what happened to it*, including items deliberately
declined.

Three kinds of item, **numbered separately** because the number is what
every cross-reference in the repo cites. Numbers are never reused or
renumbered, even when a row is struck.

- **FR-n, feature request.** Something the app does not do. The open
  question is *whether to build it*; the section below the tables holds the
  sizing, the traps and the options.
- **TR-n, triage request.** Shipped behavior is wrong **and the cause is
  not yet known**. The open question is *what is actually happening*. A TR
  closes when it is diagnosed: into a fix, into an FR when the answer is
  "we never built that", or into a decline with the mechanism written down.
- **S-n, security finding.** A way this app could expose user data or
  secrets. The open question is *what to do about the risk*; a finding can
  close as **Accepted** with the reason recorded.

Scope boundaries:

- **Not the in-flight plan.** Designed, in-progress work lives in its own
  doc and is deleted when it lands. This file survives the whole project.
- **Not a bug list.** A defect whose cause is known is fixed, not filed.
- **Not the as-built truth.** Shipped behavior is documented in the
  subsystem docs under [docs/](docs/); a row keeps only the request, the
  date and the version.
- **Not the closed detail.** Closed rows stay (this file indexes every
  number) but their sections move verbatim to
  [docs/closed/](docs/closed/), routed by
  [docs/CLOSED_ITEMS.md](docs/CLOSED_ITEMS.md). Reading this file top to
  bottom is reading the open work.

How to file, close, and grade severity: see the closing rules in
[docs/CLOSED_ITEMS.md](docs/CLOSED_ITEMS.md) and the queue in
[docs/roadmap-priorities.md](docs/roadmap-priorities.md). Closing a TR
records the **mechanism**, not just the fix. Severity: **High** is user
data or a credential leaving the machine in ordinary use; **Medium** is the
same under unusual conditions, or a missing control with no exposure
today; **Low** is nuisance or already-public exposure. A release gate
reads "no open High".

Current version: **0.1.0**.

## Feature requests, open: in progress or unbuilt

| # | Request | Requested | State |
|---|---------|-----------|-------|
| FR-1 | Native Linux packaging: Flatpak, then .deb/.rpm | 2026-08-19 | Deferred until near the full release, per owner |
| FR-2 | Lower the Linux glibc floor (build on the oldest available runner) | 2026-08-19 | Awaiting owner decision on target distros |
| FR-3 | Screenplay exporters: Fountain, Final Draft (.fdx), styled DOCX | 2026-08-24 | Built and unit-tested; awaiting the manual pass in real Final Draft and Word |
| FR-4 | Per-line geometry on scanned pages, for the screenplay classifier | 2026-08-24 | Unbuilt. Sized below; born-digital geometry shipped with FR-3 |

## Feature requests, closed: shipped, resolved or declined

Every Request link points into [docs/closed/](docs/closed/).

| # | Request | Requested | Outcome | Closed | Version |
|---|---------|-----------|---------|--------|---------|
| FR-5 | [FDX `&lt;DualDialogue&gt;` wrapper](docs/closed/fr-5.md) | 2026-08-24 | Shipped: shape confirmed from owner-supplied samples cross-checked against an importer that reads real Final Draft output, and pinned against a reference file in `tests/data/fdx/` | 2026-08-24 | 0.1.0 |

## Triage requests, open: reported, cause unknown

| # | Report | Reported | State |
|---|--------|----------|-------|

## Triage requests, closed: diagnosed

| # | Report | Reported | Outcome | Closed | Version |
|---|--------|----------|---------|--------|---------|
| TR-1 | [Tab pages intermittently paint on top of each other ("crushed/jumbled text") after opening a fresh PDF](docs/closed/tr-1.md) | 2026-08-19 | Fixed: four contributing defects on the import path removed and a single-visible-page invariant enforced and logged. Trigger never reproduced; closed on a traced interactive confirmation pass | 2026-08-19 | 0.1.0 |

## Security findings, open: exposed or unmitigated

| # | Finding | Severity | Found | State |
|---|---------|----------|-------|-------|

## Security findings, closed: fixed, accepted or declined

| # | Finding | Severity | Found | Outcome | Closed | Version |
|---|---------|----------|-------|---------|--------|---------|

---

## FR-3: screenplay exporters

**Request**: make the tool useful to actors, directors and screenwriters by
exporting a script as a script. Fountain first (open spec, whole ecosystem
reads it), Final Draft second (what the industry opens files in), styled
DOCX third (how stage plays circulate, since theatre has no interchange
standard).

**The part that was not obvious**: the serializers are small. The
classification step under them is the work. Fountain and FDX both need to
know that one block is a Character cue and the next is Dialogue, and nothing
upstream records that. As-built behavior is in
[docs/PIPELINE.md](docs/PIPELINE.md).

**The geometry gap, found during sizing.** The original sizing assumed
coordinates were already available internally. They are, for one of the two
extraction paths:

- Born-digital pages have a normalized box per character from
  `pdf_io.page_glyphs`. Real geometry, already computed, and previously
  discarded before export.
- Scanned pages have none. The VLM returns free-form Markdown, the manifest
  declares `bbox_output: false`, and `PageResult` is
  `(markdown, engine_id, duration_s)`, so the engine return type could not
  carry boxes even if an engine produced them. Tesseract parses TSV line
  boxes and already runs on every scanned page for the disagreement flag,
  but it discards the text column and is never aligned to the VLM's output.

FR-3 therefore takes the geometry where it is free (born-digital,
re-derived at export time from the source PDF, no schema change) and FR-4
carries the rest.

**Options considered and rejected**, so they are not re-proposed:

- **Make the element stream the canonical intermediate** and re-derive
  Markdown from it. Rejected: that makes screenplay classification a hard
  dependency of ordinary Markdown export, for the 99% of documents that are
  not screenplays. The stream is an ephemeral export-time projection
  instead, which keeps the spec's one-stored-representation rule intact.
- **Write indentation into the Markdown blob** so the classifier could read
  columns off the stored text. Rejected: a four-space leading indent is a
  code block in CommonMark, `normalize_markdown` preserves leading indent,
  and the prose DOCX renderer would silently set every dialogue line in
  Consolas 9pt. Geometry travels as a side channel keyed to line index.
- **A bundled .docx template** for the screenplay styles. Rejected: a binary
  no diff can review, no test can assert against, and that has to be
  regenerated by hand in Word whenever an indent changes. The styles are
  built programmatically from one table.
- **Pandoc** for format conversion. Not available: GPL, and banned by the
  license gate.

**FDX shapes that had no verified sample at first cut**: the
`<DualDialogue>` wrapper, closed as [FR-5](docs/closed/fr-5.md), and
`<TitlePage>`, still open. Title fields are written as leading `General`
paragraphs, which Final Draft opens without complaint; the real element is a
`HeaderAndFooter` plus centered paragraphs carrying layout attributes, and
no export was available to pin it. Note there is **no official FDX XSD or
DTD**, so nothing can validate an FDX in the strict sense;
`tests/fdxcheck.py` is a structural checker, not a schema.

**Traps worth keeping**: `FADE IN:` is Action, not a Transition (a real
Final Draft export emits it that way, and Fountain's auto-detect only fires
on lines ending in `TO:`). `>` collides between Markdown blockquotes and
Fountain transitions, resolved on whether the rest of the line is uppercase.
PDFium's raw text order emits no blank lines at all, so every born-digital
page arrives unblanked and the classifier's blank-line cue test carries no
information there. `scripts/check_dashes.py` bans the em dash that
screenplay dialogue uses constantly, so fixture text is ASCII.

## FR-4: per-line geometry on scanned pages

**Request**: give the screenplay classifier column positions on scanned
pages, where it currently has none. Also the prerequisite for detecting
dual dialogue by x-range overlap.

**Sizing**: larger than all three exporters combined. It needs Tesseract's
`line_boxes` to retain the TSV text column, a fuzzy alignment of VLM output
lines onto Tesseract line boxes (unreliable in a way the born-digital
alignment is not, because the two sides do not share a source), a geometry
field on `PageResult` and so a change to the `OCREngine` return contract, a
persisted `page_lines` table with a `SCHEMA_VERSION` bump, and the render
scale recorded, since normalized-to-image and normalized-to-page-box differ
once `fit_to_longest_edge` and deskew have run.

**Evidence for priority**: compare classification of the same script
born-digital and scanned. The born-digital path already classifies correctly
from geometry; the scanned path falls back to lexical rules that handle
standard formatting but misread a line of uppercase action as a character
cue.
