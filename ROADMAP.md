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

## Triage requests, closed: diagnosed

| # | Report | Reported | Outcome | Closed | Version |
|---|--------|----------|---------|--------|---------|
| TR-1 | [Tab pages intermittently paint on top of each other ("crushed/jumbled text") after opening a fresh PDF](docs/closed/tr-1.md) | 2026-08-19 | Fixed: four contributing defects on the import path removed and a single-visible-page invariant enforced and logged. Trigger never reproduced; closed on a traced interactive confirmation pass | 2026-08-19 | 0.1.0 |

## Security findings, open: exposed or unmitigated

| # | Finding | Severity | Found | State |
|---|---------|----------|-------|-------|

## Security findings, closed: fixed, accepted or declined

| # | Finding | Severity | Found | Outcome | Closed | Version |
|---|---------|----------|-------|---------|--------|---------|
