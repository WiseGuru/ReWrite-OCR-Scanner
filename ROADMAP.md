# Roadmap: feature, triage and security items

Standing register of **requested but unbuilt** work, with the date each item
was requested and the version it shipped in. It is the durable record of
*what was asked for and what happened to it*, including items deliberately
declined.

Three kinds of item, **numbered separately** because the number is what
every cross-reference in the repo cites. Numbers are never reused or
renumbered, even when a row is struck.

- **FR-n, feature request.** Something the app does not do. The open
  question is *whether to build it*; the section below the tables holds the
  sizing, the traps and the options.
- **TR-n, triage request.** Shipped behavior is wrong **and the cause is
  not yet known**. The open question is *what is actually happening*. A TR
  closes when it is diagnosed: into a fix, into an FR when the answer is
  "we never built that", or into a decline with the mechanism written down.
- **S-n, security finding.** A way this app could expose user data or
  secrets. The open question is *what to do about the risk*; a finding can
  close as **Accepted** with the reason recorded.

Scope boundaries:

- **Not the in-flight plan.** Designed, in-progress work lives in its own
  doc and is deleted when it lands. This file survives the whole project.
- **Not a bug list.** A defect whose cause is known is fixed, not filed.
- **Not the as-built truth.** Shipped behavior is documented in the
  subsystem docs under [docs/](docs/); a row keeps only the request, the
  date and the version.
- **Not the closed detail.** Closed rows stay (this file indexes every
  number) but their sections move verbatim to
  [docs/closed/](docs/closed/), routed by
  [docs/CLOSED_ITEMS.md](docs/CLOSED_ITEMS.md). Reading this file top to
  bottom is reading the open work.

How to file, close, and grade severity: see the closing rules in
[docs/CLOSED_ITEMS.md](docs/CLOSED_ITEMS.md) and the queue in
[docs/roadmap-priorities.md](docs/roadmap-priorities.md). Closing a TR
records the **mechanism**, not just the fix. Severity: **High** is user
data or a credential leaving the machine in ordinary use; **Medium** is the
same under unusual conditions, or a missing control with no exposure
today; **Low** is nuisance or already-public exposure. A release gate
reads "no open High".

Current version: **0.1.0**.

## Feature requests, open: in progress or unbuilt

| # | Request | Requested | State |
|---|---------|-----------|-------|
| FR-1 | Native Linux packaging: Flatpak, then .deb/.rpm | 2026-08-19 | Deferred until near the full release, per owner |
| FR-2 | Lower the Linux glibc floor (build on the oldest available runner) | 2026-08-19 | Awaiting owner decision on target distros |

## Feature requests, closed: shipped, resolved or declined

Every Request link points into [docs/closed/](docs/closed/).

| # | Request | Requested | Outcome | Closed | Version |
|---|---------|-----------|---------|--------|---------|

## Triage requests, open: reported, cause unknown

| # | Report | Reported | State |
|---|--------|----------|-------|
| TR-1 | Tab pages intermittently paint on top of each other ("crushed/jumbled text") after opening a fresh PDF | 2026-08-19 | Investigating; real widget-visibility fault isolated, trigger not yet reproduced under scripting |

## Triage requests, closed: diagnosed

| # | Report | Reported | Outcome | Closed | Version |
|---|--------|----------|---------|--------|---------|

## Security findings, open: exposed or unmitigated

| # | Finding | Severity | Found | State |
|---|---------|----------|-------|-------|

## Security findings, closed: fixed, accepted or declined

| # | Finding | Severity | Found | Outcome | Closed | Version |
|---|---------|----------|-------|---------|--------|---------|

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
  interactive path: a previous project open with Review current, then
  File > Open through the native QFileDialog.
- No Python exceptions in logs during reproductions.

**Hardened while investigating** (real defects fixed on the way, none of
which closed the symptom): thumbnail QPixmaps were created on a worker
thread (undefined behavior; now QImage handoff), the thumbnail loader
starved the GUI thread on the global PDFium lock (now yields between
pages), and synchronous page renders on the GUI thread blocked tabs' first
layout pass (all page renders now run on an async render worker).

**Next steps**:

1. Reproduce under the exact interactive flow, native file dialog
   included: the native dialog runs its own event loop and is the main
   untested difference from the scripted flow.
2. Instrument `currentChanged` plus per-page visibility after each switch
   in that flow to catch the first unhidden page and what preceded it.
3. If the native dialog correlates, test `QFileDialog.DontUseNativeDialog`
   as diagnostic and candidate workaround.
4. Pin PySide6 6.8 LTS and retry to rule a 6.11 regression in or out.
