## TR-1: tab pages paint on top of each other after opening a fresh PDF

**Symptom**: after opening a not-previously-opened PDF through the Import
button, the text of two tab pages renders superimposed (for example the
Review header over the Extract header: "Show:" and "Engine:" merged). It
self-heals after switching tabs a few times. Resuming a previously-opened
PDF does not show it. Observed on Windows 11, PySide6 6.11.2.

**Established facts** (2026-08-19):

- Widget-state dumps during a live reproduction show two `QStackedWidget`
  pages with `isVisible() == True` simultaneously (for example
  current=Review while ExtractTab is also visible). It is genuine widget
  visibility, not stale backing-store pixels: a `window.grab()` widget-tree
  render shows the same overlap.
- Show/hide tracing across a reproduction shows tab switches delivering
  `showEvent` to the incoming page with **no `hideEvent` to the outgoing
  page**; only ImportTab ever received a hide.
- A minimal pure-Qt QTabWidget (same PySide6 6.11.2 environment), including
  the app's tab enable/disable dance, behaves correctly.
- Scripted bisects neutralizing the Rules-tab showEvent override, the
  thumbnail loader, and the Review-tab shortcuts all came back clean, but
  so did the unmodified app under the same scripted flow: the scripted
  reproduction lost the trigger. The failing flow appears to need the
  interactive path: a previous project open, then Open PDF through the
  native QFileDialog.
- No Python exceptions in logs during reproductions.

**Ruled out by direct probe of PySide6 6.11.2** (2026-08-19), so they are
not worth re-testing: the tab enable/disable loop on its own,
`setCurrentIndex` onto a disabled tab, and a re-entrant `setCurrentIndex`
raised from a page's own `showEvent`. All three hold the one-visible-page
invariant, including under 20,000 fuzzed tab operations. No tab rebuilds
its layout and no application code calls `show`, `hide` or `setParent` on
a tab page, so Qt itself is the only thing that shows a page.

**Contributing defects found and fixed** (2026-08-19). None is proven to be
*the* trigger, because the trigger was never reproduced under scripting,
but each is a real fault on the failing path and each could produce a stray
visible page or an unlaid-out one:

- `project_closed` fired **twice** per import: `ImportTab._start_open` and
  `ProjectContext.attach_project` both called `close_project`, which had no
  "was anything open" guard. Every subscriber, including the tab
  enable/disable pass, therefore ran twice per open.
- `PageStrip` connected `currentRowChanged` straight through to
  `page_selected`, and `MainWindow._on_strip_selected` responded by
  switching to the Review tab with no open-project or tab-enabled guard.
  Clearing and refilling the strip moves the current row on its own, so a
  repopulation could switch tabs in the middle of a project open, and a
  focus-in on a freshly cleared list makes Qt select row 0 by itself.
- Disabling the tabs while one of them was current made Qt pick its own
  replacement index, walking the stack a page at a time on the way out.
- The GUI thread blocked inside the very handlers that change page
  visibility: `ImportTab.open_path` opened the PDF synchronously for its
  encryption probe while the outgoing document's thumbnail loader held the
  global pdfium lock, and `PageStrip._stop_loader` waited up to five
  seconds on that loader from a `project_closed` handler. A GUI thread
  blocked at that moment is exactly what makes a tab miss its first layout
  pass and paint every child stacked at the top left, which is what the
  reported screenshot shows.

**Hardened earlier while investigating**: thumbnail QPixmaps were created
on a worker thread (undefined behavior; now a QImage handoff), the
thumbnail loader starved the GUI thread on the global PDFium lock (now
yields between pages), and synchronous page renders on the GUI thread
blocked tabs' first layout pass (all page renders now run on an async
render worker).

**Standing guard** (shipped, agreed with the owner):
`MainWindow._enforce_single_page` asserts on every tab change that exactly
one page is visible and that it is the current one, corrects any stray, and
logs a warning naming the strays and the recent transitions.
`REWRITEOCR_DEBUG_TABS=1` adds a per-transition trace with call stacks. A
recurrence arrives as a log line instead of a screenshot. As-built detail
lives in [../UI-JOBS.md](../UI-JOBS.md).

**Confirmation pass** (2026-08-19, owner, Windows 11, PySide6 6.11.2): two
traced runs of the real interactive flow, native file dialog included.
The second covered four opens through the Import button with fresh
never-opened PDFs, extractions and llama-server runs in between, and 23 tab
transitions: no overlap, and the guard logged no correction. Closed on that
evidence. **The trigger itself was never reproduced**, so this closes on
"contributing defects removed and the invariant enforced", not on a single
proven cause. If it ever recurs, the guard's warning names the strays and
the preceding transitions; if the symptom returned with no warning, the
untried step is pinning PySide6 6.8 LTS to rule a 6.11 regression in or
out.
