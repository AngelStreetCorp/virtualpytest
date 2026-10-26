# BUG-0830 — Clicking the "runs failed" notification lands on the dashboard, not on the failing runs

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                    |
|-----------|------------------------------------------|
| ID        | BUG-0830                                 |
| Reported  | 2026-10-22                               |
| Status    | Fixed (pending deploy)                   |
| Severity  | Low                                      |
| Area      | frontend (dashboardAlerts)               |
| Fixed in  | build 90145 |
| Commit    | TBD                                      |

---

## Symptom

The bell shows "78 of 240 runs failed". Clicking it does not open the failing runs: the browser goes to
the dashboard (`/`), the same page the notification was raised from. The expected destination is the
reports page narrowed to the failed runs.

## Root cause

`detectProblems()` in `frontend/src/components/dashboard/dashboardAlerts.ts` built the failure-spike
problem with a placeholder target, `to: '/'`, while every other problem in the same function carries
the page that actually shows the cause (`/status?host=…`, `/monitoring/ai-usage`, the device deep link).

`NotificationBell` navigates to exactly that field (`navigate(n.to)` in
`frontend/src/components/notifications/NotificationBell.tsx`), so the placeholder was the whole defect:
the alert was wired to the dashboard and the dashboard happened to be its own origin, which is why it
read as "nothing happened" rather than as a wrong page.

The destination was already available. The reports page reads `?status=` and `?range=` as deep links
(TASK-123, `TestReports.tsx`), and `DASH_LINKS.reports()` in `frontend/src/components/dashboard/dashboardLinks.ts`
is the helper that builds them — the Failures KPI tile on the same dashboard already links to
`/test-results/reports?status=failed&range=24h`.

## Fix

One line in `detectProblems()`: the spike problem now carries
`DASH_LINKS.reports({ status: 'failed', range: summary.range })`. `summary.range` is the window the
`78 of 240` counts were computed over, so the linked list is the same set the alert describes instead of
the whole history. The toast's "Show" action inherits the same `to`, so both entry points move together.

`frontend/src/components/dashboard/dashboardAlerts.test.ts` gained a case pinning the URL for two
ranges; it fails on the old code with `Received: "/"`.

## Verification

- `vitest run src/components/dashboard src/components/notifications` — 116 passed (11 files).
- `tsc --noEmit` and `eslint` on the two changed files — clean.
- Manual, on the deployed build: open the dashboard until the spike fires, click the bell entry, and
  land on `/test-results/reports?status=failed&range=24h` with only the failed runs listed. Repeat with
  the dashboard range set to 7d and confirm `range=7d` follows.