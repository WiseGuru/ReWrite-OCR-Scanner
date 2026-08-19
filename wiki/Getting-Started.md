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

Choose Markdown or Word (.docx), page-break handling, and whether to apply
cross-page cleanup: rejoining words hyphenated across page breaks, dropping
running headers and page numbers that appear on most pages, and merging
tables that continue across a page boundary. If flagged pages are still
unreviewed, the app lists them and asks before exporting. Figures are
written as real image files in a `_figures` folder next to your export.
