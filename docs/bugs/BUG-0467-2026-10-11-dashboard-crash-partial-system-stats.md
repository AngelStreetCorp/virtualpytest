# BUG-0467 — Dashboard crashes on a host whose system_stats has no usage numbers

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0467                                                     |
| Reported  | 2026-10-11                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

`/dashboard` shows the route error boundary: `TypeError: Cannot read properties of undefined (reading 'toFixed')` in the Dashboard chunk.

## Root cause

The lightweight `/server/system/getAllHosts` payload (`include_system_stats=false`,
`backend_server/src/routes/server_system_routes.py`) sends a partial `system_stats` —
`platform`, `hardware_encode`, `archive_video` — with no CPU/RAM/disk numbers. When that host
object reached the Dashboard, `SystemStatsDisplay` in `frontend/src/pages/Dashboard.tsx` only
checked `!systemStats` (a non-empty object passes) and called `cpu_percent.toFixed(0)` on
`undefined`. The server-header chips had the same guard.

## Fix

`SystemStatsDisplay` and the server-header chips render only when `cpu_percent` is a number;
otherwise the host shows "No system stats available" until the full stats arrive.

## Verification

Open `/dashboard`: the page renders, host cards show usage once the full-stats poll lands.
