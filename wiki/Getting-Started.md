# Getting started

The main window is a five-step tab bar: Import, Rules, Extract, Review,
Export. You can move freely between tabs once a document is open; the left
strip always shows every page with badges for its type (T = text layer,
S = scanned, M = mixed), a colored dot for flag severity, and a check when
you mark it reviewed. Opening a document highlights page 1 there; clicking
any page opens it in Review.

## 1. Import

Open a PDF. The app classifies every page in seconds and shows a summary
such as "287 pages: 12 scanned, 275 with a usable text layer". Pages with a
real text layer are converted directly and never touch the AI model, which
is the biggest speed win in the whole app. Password-protected PDFs prompt
for the password.

If you opened this PDF before, the app finds your earlier progress
automatically, even if the file was moved or renamed; see [[Data-Storage]].

## 2. Rules (optional)

Skip this unless you already know the document's layout. Here you can draw
exclude boxes over running headers, footers, and page numbers, or column
boxes to fix reading order, scoped to all, odd, even, a page range, or one
page. Details in [[Region-Rules-and-Annotation]].

## 3. Extract

Press Start. You get per-page progress, an estimated time remaining, and
the device in use (GPU or CPU). Pause, resume, and cancel are always
available; finished pages are saved immediately, so cancelling or even a
crash never loses completed work. While the AI model reads a page on the
GPU, Tesseract reads the same page on the CPU as an accuracy cross-check.

## 4. Review

Extraction drops you into review, showing flagged pages first, worst
first. Each flag comes with a plain-language explanation (for example,
"Output repeats the same phrase 40 times, which usually means extraction
failed"). The page image sits on the left, editable Markdown on the right;
edits save automatically and always win over the engine output.

Keyboard: **N** next, **P** previous, **Ctrl+Enter** mark reviewed and
advance, **Ctrl+D** mark needs work. For a page that keeps looping there is
a one-click "Retry (higher repeat penalty)". For layout problems, "Annotate
and re-extract..." opens the region canvas for just that page.

## 5. Export

Choose a format, page-break handling, and whether to apply cross-page
cleanup: rejoining words hyphenated across page breaks, dropping running
headers and page numbers that appear on most pages, and merging tables that
continue across a page boundary. If flagged pages are still unreviewed, the
app lists them and asks before exporting. Figures are written as real image
files in a `_figures` folder next to your export.

A prose document exports as **Markdown** or **Word (.docx)**. A screenplay
adds three more formats; see below.

## Screenplays and stage plays

Set **Document type** to "Screenplay or stage play" on the Import tab, or
from the same control on the Export tab if you picked wrong. The setting is
remembered with the project.

Export then offers:

| Format | Opens in |
|---|---|
| Fountain (.fountain) | Highland, Slugline, Beat, WriterDuet, Trelby |
| Final Draft (.fdx) | Final Draft |
| Screenplay Word (.docx) | Word, and anything that reads paragraph styles |

Each block is classified as a scene heading, action, character cue,
parenthetical, dialogue or transition before the file is written, so the
script opens with its structure intact rather than as plain paragraphs. The
Word file carries real named styles at the conventional indents (character
cue 3.5 inches from the paper edge, dialogue 2.5, parenthetical 3.0,
transition 5.5) in Courier 12pt, which is what stage plays circulate as.

Page numbers, `CONTINUED:` and `(MORE)` are removed. The result line after
an export says how many elements were classified, how many character cues
were uncertain, and how much page furniture was dropped. If a cue is
reported as uncertain, check that line in the output.

Both layouts are handled: a **screenplay**, where the character cue sits in
its own column above the dialogue, and a **stage play** in the published
form where the cue is inline, as in `KEN. I am not scared.` For a stage
play the app first works out the cast from the names that begin lines, then
separates every speech, including exchanges that OCR ran together into a
single paragraph. `ACT ONE`, `Scene 3`, `PROLOGUE` and `INTERMISSION` are
recognized as act and scene divisions.

Accuracy is best on a PDF exported from a screenwriting tool: the app can
read the exact column each line starts in, which is the strongest signal a
screenplay has. On a scanned script it works from the text alone, which
handles standard formatting well but can misread a line of ALL CAPS action
as a character name.

The page-break option does not apply to these formats. Final Draft and Word
both repaginate a script when they open it, so forcing the scan's page
boundaries would only produce short pages.

**Side-by-side (dual) dialogue** is carried through to both Fountain and
Final Draft when the source marks it, so a script that already had it keeps
it. It is not inferred from an unmarked scan: two speeches printed side by
side arrive as two ordinary speeches, and nothing in the text distinguishes
them from two speeches in sequence.

One other limit: Final Draft files carry their title fields as plain
paragraphs rather than a Final Draft title page.
