# UI and job queue

Update this doc in the same change as any behavior it describes.

## Layering rule

The UI never calls engines or the pipeline directly; all work goes through
the job queue so pause/resume/cancel and progress are uniform. `core/`,
`pipeline/`, and `engines/` never import Qt; `jobs/` is the only bridge.

## Job queue (`jobs/`)

- `JobControl` (Qt-free): cancel and pause `threading.Event`s;
  `checkpoint()` blocks while paused and raises `JobCancelled` when
  cancelled. Pipelines call it between pages and between download chunks.
- `JobQueue` (GUI thread) owns one persistent `QThread` hosting a
  `JobRunner` (moveToThread pattern). FIFO, one job at a time; queued
  signal connections deliver progress/page_done/device/message/finished/
  failed/cancelled on the GUI thread. `_SignalReporter` adapts the
  pipeline's plain-callback `Reporter` protocol onto those signals.
- Jobs (`jobs/definitions.py`) are Qt-free and open their own `SidecarDB`
  inside `run()` (SQLite thread rule): `OpenProjectJob` (hash, sidecar
  lookup/migration, triage; see docs/DATA-MODEL.md), `ExtractJob`,
  `ExportJob`, `DownloadModelJob`, `DiscardSidecarJob`.

## UI structure (`ui/`)

`MainWindow` = five-tab wizard (Import, Rules, Extract, Review, Export;
free navigation once a project is open) plus the persistent `PageStrip`
dock (thumbnails loaded by a background QThread; badges for
classification, worst flag severity, review status). `ProjectContext`
(`ui/state.py`) is the shared state object: open document, GUI-thread
`SidecarDB`, model selection persisted in settings, bounded-LRU page
render cache honoring rotation and stored deskew, and the signals tabs
subscribe to (`project_opened`, `page_updated`, `regions_changed`,
`device_changed`). MainWindow forwards every job's `page_done` to
`context.page_updated` so the strip and review tab refresh live.

pdfium is not thread-safe even across documents: every call anywhere goes
through the module-global lock in `core/pdf_io.py`, which is what makes
the GUI-thread renders and worker-thread extraction coexist.

## Tab and page-strip invariants

Three rules keep the tab stack honest. They exist because of TR-1, where
two stack pages painted at once after an import (see
[closed/tr-1.md](closed/tr-1.md)).

- **Every tab change goes through `MainWindow._go_to_tab`.** It sets the
  index, activates the incoming page's layout (a tab shown for the first
  time while the GUI thread is busy can otherwise miss its first layout
  pass and paint every child stacked at the top left), then runs
  `_enforce_single_page`.
- **`_enforce_single_page` is the standing invariant**: exactly one page is
  visible and it is the current one. It runs on every `currentChanged` and
  again on the next turn of the event loop, corrects any stray, and logs a
  warning naming the strays and the recent tab transitions.
  `REWRITEOCR_DEBUG_TABS=1` adds a per-transition trace with call stacks.
- **The page strip emits `page_selected` only for a genuine user
  selection.** Clearing and refilling the list moves the current row on its
  own, and `MainWindow._on_strip_selected` switches to the Review tab, so
  an unfiltered `currentRowChanged` could change tabs in the middle of a
  project open. `PageStrip` suppresses the signal while `_populating` and
  when no project is open, and always leaves a valid current row behind,
  because a list with none of its own makes Qt select row 0 as soon as the
  widget takes focus.

Two related rules on blocking: `PageStrip` retires a superseded thumbnail
loader without waiting on it (`_stop_loader` disconnects, interrupts and
defers deletion; `shutdown()` at window close is the only place that
waits), and `ImportTab.open_path` calls
`ProjectContext.quiesce_background_work()` before its synchronous
encryption probe, so the GUI thread never queues behind a background render
pass on the pdfium lock while the tabs are being swapped.

## Review tab behaviors worth knowing

- Filter defaults to flagged-only when flags exist; flagged navigation is
  sorted by worst severity descending.
- Edits debounce-save to `edited_text`; text identical to the engine
  output stores NULL (so re-extraction warnings only fire for real edits).
- "Retry (higher repeat penalty)" is enabled only when a repetition flag
  is present and a model is selected; it re-extracts that page with
  `repeat_penalty + 0.25`.
- Keyboard: N/P navigate, Ctrl+Enter mark reviewed and advance, Ctrl+D
  needs work.

## Annotation canvas (`ui/canvas/`)

`PageScene` (pixmap + draw-mode rubber band) + `RegionItem`
(QGraphicsRectItem with kind color, order badge, eight resize handles) +
`AnnotationView` (Ctrl+wheel zoom, middle-drag pan) +
`RegionController`, the testable brain: converts scene pixels to
normalized page coordinates at the boundary, persists committed changes,
renumbers explicit order badges, and snaps new region edges outward to
Tesseract line boxes when available (disabled with a note otherwise).
Two modes: `global` (Rules tab; scope from the scope selector) and `page`
(AnnotateDialog from review; scope pinned to that page). The Rules tab
preview renders the overlay on first/middle/last pages of the document.

## Dialogs

`ModelDownloadDialog` (quant choice with plain-language tradeoffs, license
acknowledgment gate, resumable progress), `AnnotateDialog`,
`DiagnosticsDialog` (copy diagnostic block), `AboutDialog` (bundled
license texts from `resources/licenses/`, regenerated by
`scripts/collect_licenses.py`).
