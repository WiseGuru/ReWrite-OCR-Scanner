# Data storage

The source PDF is never modified, and nothing is written next to it. All
application data lives in one per-user folder:

- Windows: `%LOCALAPPDATA%\ReWriteOCR`
- Linux: `~/.local/share/ReWriteOCR` (or `$XDG_DATA_HOME/ReWriteOCR`)

| Subfolder | Contents |
|---|---|
| `projects/` | one `.ocrproj` project file per PDF, plus its extracted figure images |
| `models/` | downloaded model weights |
| `profiles/` | saved region profiles |
| `logs/` | application and model-runtime logs |
| `temp/` | short-lived working files, cleaned automatically |

## Projects and resuming

Everything you do (page classifications, extracted and edited text, flags,
regions, review status) is saved continuously to the project file, page by
page. You can close the app mid-extraction and continue later; a crash
never loses completed pages.

Reopening a PDF finds its project automatically. This works by content, so
it survives moving or renaming the PDF. If the PDF's *content* changes
(for example, it was regenerated), the app warns that your saved progress
belongs to a different version and offers to open read-only or discard the
old progress.

## Uninstalling and cleanup

Uninstalling the app leaves this data folder untouched, so your projects
and downloaded models survive reinstall or upgrade. Delete the folder
itself to remove everything; delete `models/` alone to reclaim the model
download space (the app offers to re-download when needed).
