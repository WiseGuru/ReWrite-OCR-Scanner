# Troubleshooting

## What the flags mean

| Flag | Meaning | What to do |
|---|---|---|
| Repetition | The output repeats a phrase or ends in a loop, the signature failure of vision OCR models. | Use "Retry (higher repeat penalty)" on that page; if it persists, annotate the problem area (often a very short fragment or odd layout) and re-extract. |
| Low yield | The page looks dense but extraction returned almost nothing. | Check rotation, then re-extract; for partial pages, draw column regions around the real content. |
| Engine disagreement | The AI model and Tesseract read the page very differently; one of them is probably wrong. | Read the page in Review and correct or accept; this flag needs Tesseract installed. |

## GPU and performance

- "Running on CPU" means the GPU could not initialize or failed mid-run;
  the app continues correctly but more slowly. Common causes: outdated GPU
  drivers (Vulkan), or another program holding GPU memory.
- The first extraction after choosing a model is slower while the model
  loads; subsequent pages stream steadily.

## Common situations

- **"llama-server was not found"**: install llama.cpp
  (see [[Installation]]) or set its path in settings. Until then, scanned
  pages fall back to Tesseract when available.
- **Password-protected PDF**: you are prompted for the password. If the
  file uses an unsupported encryption scheme, the app says so; decrypt
  with another tool first.
- **Damaged PDF**: readable pages are processed; unreadable pages are
  listed explicitly as failed rather than aborting the run.
- **"Source file changed"**: the PDF's content differs from when the
  project was created; see [[Data-Storage]].
- **Region edge snapping is off**: Tesseract is not installed
  (see [[Installation]]).

## Known limitations

- Handwriting recognition is weak across all supported models; this is a
  printed-document tool.
- Language coverage skews toward Latin-script and European languages.
  Verify CJK, Arabic, and Indic scripts per document before relying on
  results; Tesseract's language packs cover the long tail at lower
  structural fidelity.
- Complex tables (merged cells, nested headers, multi-page continuation)
  degrade; the table region in [[Region-Rules-and-Annotation]] exists for
  exactly these.
- Review output before use anywhere errors are costly. Flags reduce review
  effort; they do not eliminate it.

## Reporting a bug

Help > "Copy diagnostic info..." copies the app version, OS, device, model
identity (including its exact revision), and the current page's flags:
paste that block into your report. The log file lives in the `logs/`
folder described in [[Data-Storage]].
