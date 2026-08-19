# ReWrite OCR Scanner

ReWrite OCR Scanner converts PDFs into clean Markdown or Word documents on
your own machine. A local AI vision model reads scanned pages; pages that
already contain real text are converted directly without any model. Nothing
leaves your computer, and no network access is needed after the one-time
model download.

The design goal: a 300-page scanned book becomes clean Markdown or DOCX in
one session, with roughly 10 to 30 flagged pages to review instead of all
300.

## Start here

- [[Installation]]: installers for Windows and Linux, and what else you
  need (llama.cpp, optionally Tesseract).
- [[Getting-Started]]: the five-step workflow from PDF to export.
- [[Models]]: which OCR models are available and how downloads work.

## Going deeper

- [[Region-Rules-and-Annotation]]: fixing headers, footers, reading order,
  tables, and figures with drawn regions.
- [[Data-Storage]]: where your projects, models, and settings live.
- [[Troubleshooting]]: what the flags mean, GPU versus CPU, and known
  limitations.
