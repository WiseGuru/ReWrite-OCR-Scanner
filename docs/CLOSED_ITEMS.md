# Closed items: the record behind everything already resolved

**The detail for every `FR`, `TR` and `S` that is finished.** Each closed
section is its own file under [closed/](closed/), named for its number:
`closed/fr-1.md`, `closed/tr-1.md`, `closed/s-1.md`. Sections move there
verbatim when their row closes, so the live register stays a short read
while the evidence, the mechanisms and the declined options stay findable.

**This file is the router, and nothing more.** It maps a number to the file
holding its section, and carries no outcome, date, version or summary: each
of those has exactly one owner, the register row in
[../ROADMAP.md](../ROADMAP.md).

Standing rules: a closed section is never edited (a settled decision that
turns out wrong gets a new row linking back); the archive is not the
as-built truth (behavior lives in the subsystem docs); nothing is ever
renumbered.

## How to close something into the archive

1. Move the row to the matching **Closed** table in
   [../ROADMAP.md](../ROADMAP.md) with its outcome, date and version.
2. Write the whole `## <id>:` section to `docs/closed/<id>.md`
   **unchanged**, heading levels intact, and point the row's link at it.
3. Move anything now as-built into its subsystem doc first.
4. Add the row to the map below and repoint any anchored cross-references.

## The map

Number order within each kind, matching the register.

### Feature requests

| # | Section |
|---|---------|
| FR-5 | [closed/fr-5.md](closed/fr-5.md) |

### Triage requests

| # | Section |
|---|---------|
| TR-1 | [closed/tr-1.md](closed/tr-1.md) |

### Security findings

| # | Section |
|---|---------|
