# BUG-0149 — The dashboard's "errors only" filter outlived the errors and left an empty page

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0149                                                     |
| Reported  | 2026-09-21                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low (cosmetic dead end — no data loss, recoverable via Clear) |
| Area      | `frontend/src/pages/Dashboard.tsx`                           |
| Fixed in  | Unreleased                                                   |
| Commit    | `56731a805f`                                                 |

---

## Symptom

Clicking the red error badge on the dashboard narrows the host list to the hosts currently in
error. Once those hosts recover — a service restarted, a host came back online — the dashboard
went blank: no host cards, just "No hosts match the selected filters." The badge that switched
the filter on had disappeared with the last error, so the only way back was the `Clear` chip in
the filter bar, which reads as a filter-bar control and not as the undo for a toggle that lives
in the Hosts header.

Worse on a reload. The toggle is persisted to `localStorage`, so a user who filtered to errors
one day, fixed them, and opened the dashboard the next day landed straight on an empty page
with no indication that a filter was responsible.

## Root cause

`errorOnly` is a `usePersistedState` boolean, and nothing ever reset it. It was written by the
badge and read by `filteredServerHostsData`, which filters hosts through `hostHasError`. When
the error count reached zero the filter kept filtering — correctly, to nothing — while the badge
that renders on `errorHostCount > 0 || errorOnly` stopped showing the number that explained why.

## Fix

An effect beside `errorHostCount` in [Dashboard.tsx](../../frontend/src/pages/Dashboard.tsx)
switches `errorOnly` off as soon as the filtered scope holds hosts and none of them is in error.

Two guards keep it from firing on a scope that is empty for some other reason: it waits for
`loading` to clear, and it requires the attribute-filtered scope (target / model / tag) to
contain at least one host. Without them, a still-loading dashboard, or one narrowed to nothing
by the other filters, would look identical to "all clear" and would silently drop a toggle the
user had just set.

## Verification

On the dashboard with at least one host in error:

1. Click the red badge — only the erroring hosts remain.
2. Fix the error (or wait for the host to recover). At the next data refresh the toggle releases
   itself, the full host list returns, and the badge disappears.
3. With the toggle on, narrow the Targets filter to a host that has no error: the page still says
   "No hosts match the selected filters" and the toggle stays on — the guard leaves a
   user-narrowed empty scope alone.
