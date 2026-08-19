# Roadmap priorities: the cross-item working queue

> **This is the priority queue, not the record.** [../ROADMAP.md](../ROADMAP.md)
> owns what was requested and what happened to it, and [closed/](closed/)
> owns the evidence behind anything settled. This file only orders the
> **open** work by impact and names the next concrete action each item
> needs. **Update it in the same change as the work it schedules; delete a
> row when its item closes.** A struck-through row is a row that should
> have been deleted.
>
> Ordering agreed with the owner **2026-08-19**; last reconciled
> **2026-08-19**.
>
> Reading this file top to bottom should be reading every open thread in
> the project. The detail does not move here: each row points at its owner.

## P0: drop everything

Empty is the healthy state. An occupant here is blocking or urgent.

| # | Item | What it needs |
|---|---|---|
| TR-1 | Overlapping tab pages on fresh-PDF open | Reproduce under the interactive flow (native file dialog); see next steps in [../ROADMAP.md](../ROADMAP.md#tr-1-tab-pages-paint-on-top-of-each-other-after-opening-a-fresh-pdf) |

## P1: highest impact-per-effort

| # | Item | What it needs |
|---|---|---|
| (release) | Stable 0.1.0 | Blocked on TR-1; then a fresh prerelease tag, the manual test pass in [../RELEASING.md](../RELEASING.md), version bump, bare tag |

## P2: scheduled behind P1

| # | Item | What it needs |
|---|---|---|
| FR-2 | Lower Linux glibc floor | Owner decision: which distros must run the AppImage; then pin the release runner |
| FR-1 | Flatpak, then .deb/.rpm | Deliberately parked until near the full release |

## P3: closeout and verification debt

| # | Item | Notes |
|---|---|---|
| (chore) | Bump GitHub Actions to Node-24 majors | Deprecation warnings only today; owner: [../.github/workflows/release.yml](../.github/workflows/release.yml) and ci.yml |
