# Region rules and annotation

Regions are boxes you draw on a page to control extraction. They exist in
two places: the **Rules** tab (before extraction, applied across many
pages) and the **Annotate** dialog (from Review, applied to one page).

## Region kinds

| Kind | Effect |
|---|---|
| exclude | The area is omitted from output entirely. Use for headers, footers, page numbers, margin notes. |
| column | Defines reading order explicitly. Columns are read in their numbered order; this is the fix for garbled reading order on unusual layouts. |
| heading | Forces a heading level (1 to 6) on the text in the box, regardless of what the model inferred. |
| table | The area is read separately as a table and output as an HTML table, which survives merged cells better than a Markdown pipe table. |
| figure | The area is not transcribed. It is cropped and saved as an image file and referenced from the output. |

Drawing a table or figure box does not discard the rest of the page: the
remaining content is still read normally. Drawing column or heading boxes
switches the page to explicit layout, where only your boxes are read, in
the order shown on their badges. Order is always explicit and visible;
reorder with the order buttons, never by guessing geometry.

## Scopes (Rules tab)

Each rule applies to all pages, odd pages, even pages, a page range
(like `12-48`), or a single page. Odd/even matters for scanned books:
margins mirror between left and right pages, so a box that clears the
gutter on odd pages sits inside the text on even pages; draw one rule per
side. "Preview on three pages" renders your boxes on the first, middle,
and last page of the document so you can see where they land before
running 300 pages.

## Edge snapping

When Tesseract is installed, new region edges snap outward so no text line
is cut mid-height (a crop that slices a sentence makes the AI model invent
a completion). Column regions keep their left and right edges exactly
where you drew them, since cutting there is the point. Without Tesseract,
snapping is off and the app says so.

## Profiles

A region set can be saved as a named profile and applied to other
documents, which is the fast path for a book series or journal run with a
consistent layout. Profiles are stored independently of any document; see
[[Data-Storage]].

## Re-extraction

From Review, "Annotate and re-extract..." re-runs only that page with the
new regions. If you edited the page's text, the app warns before
overwriting your edit. Whole-document re-extraction never happens
implicitly.
