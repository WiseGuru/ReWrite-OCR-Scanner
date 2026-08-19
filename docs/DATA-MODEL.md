# Data model and storage

Update this doc in the same change as any behavior it describes.

## Where everything lives

Nothing is ever written next to the source PDF. All state is under the
per-user app data directory (`config.app_data_dir()`):
`%LOCALAPPDATA%\ReWriteOCR` on Windows, `$XDG_DATA_HOME/ReWriteOCR` or
`~/.local/share/ReWriteOCR` on Linux. Override with the `REWRITEOCR_DATA_DIR`
environment variable (tests do this per-test via a conftest fixture).

| Path | Contents |
|---|---|
| `projects/` | `.ocrproj` sidecars and their `<stem>_figures/` folders |
| `models/<model-id>/` | downloaded GGUF files, verified by SHA-256 |
| `profiles/` | saved region profiles (JSON) |
| `logs/` | rotating `rewriteocr.log` plus `llama-server.log` |
| `temp/` | engine scratch; stale entries cleaned at startup (`config.clean_stale_temp`) |
| `settings.json` | small key-value settings (`config.Settings`) |
| `license_acks.json` | per-model license acknowledgments |
| `manifest.json` | optional user-updated model manifest override |

## Sidecar (`core/sidecar.py`)

SQLite file per project, schema in `sidecar.DDL` (tables `project`, `pages`,
`regions`, `flags`, `figures`; spec section 4 is the field-level reference).
Key invariants:

- **One `SidecarDB` per thread.** Connections are `check_same_thread=True`;
  the worker job opens its own instance. WAL mode, `busy_timeout=5000`.
- **One transaction per page** (`write_page_result`: text + flags
  atomically), so a crash never loses completed pages.
- `edited_text` NULL means "use `extracted_text`"; re-extraction only
  clears it when `clear_edited=True` is passed explicitly, and the UI warns
  first.
- `model_id`/`model_revision` are stored per page for reproducible bug
  reports.
- Schema migrations key off `project.schema_version`
  (`constants.SCHEMA_VERSION`); forward-only, slotted in `check_schema`.

## Project file naming and lookup

`sidecar_path_for(pdf)` returns
`projects/<pdf-stem>-<sha1(abspath)[:10]>.ocrproj`: stable for the same
file path, collision-free for same-named PDFs in different folders.

`OpenProjectJob` resolves in this order:

1. The path-keyed sidecar. Stored `source_hash` match resumes; mismatch
   returns `hash_mismatch=True` and the UI offers read-only or discard.
2. A legacy sidecar next to the PDF (early builds wrote there): migrated
   into `projects/`, including the figures folder, with
   `rewrite_figure_prefix` fixing figure rows and Markdown image links to
   the renamed figures dir.
3. A content-hash scan over `projects/*.ocrproj`, which finds the project
   again after the PDF was moved or renamed.
4. Otherwise a fresh sidecar is created and triage runs.

`DiscardSidecarJob` removes the sidecar, its WAL/SHM journals, and its
figures folder.

## Figures

Extraction writes crops to `projects/<sidecar-stem>_figures/` and stores
paths relative to the sidecar's parent (`<dir-name>/<file>`), which is also
how Markdown references them. Export copies referenced figures to
`<output-stem>_figures/` beside the output file and rewrites the links, so
exports are self-contained (`pipeline/export_md.py`).

## Region profiles (`core/profiles.py`)

A saved region set independent of any document: JSON in `profiles/`,
containing the region rows plus name/description. Applying a profile
inserts its regions into the current project's sidecar.
