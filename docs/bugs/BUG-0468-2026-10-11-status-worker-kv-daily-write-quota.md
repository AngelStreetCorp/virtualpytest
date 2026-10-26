# BUG-0468 — Status worker exceeds the free KV daily write quota

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0468                                                     |
| Reported  | 2026-10-11                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | infra / cloudflare worker                                    |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Cloudflare emailed "Workers KV operations approaching the daily limit — 50 % reached"
on 2026-10-11, the first day of `vpt-status-worker`. On the free plan KV allows 1,000
writes and 100,000 reads per day (reset 00:00 UTC); once over, KV calls fail.

## Root cause

- **Writes:** the cron runs every minute (`crons = ["*/1 * * * *"]`) and `scheduled()`
  ended with an unconditional `STATUS_KV.put(...)` — 1,440 writes/day, over the 1,000
  quota every day from ~16:40 UTC. After that the probe state stopped being saved, so
  DOWN / RECOVERED emails could not fire until midnight.
- **Reads:** the `fetch` handler reads KV on every request to the site and `readStatus()`
  had no error handling. Past the read quota it would throw and fail every page and API
  call, not just the monitor.

## Fix

`infra/cloudflare/status-worker/src/index.ts`:

- `scheduled()` writes only when the state changes (up/down flip, alert flag flip, or
  the failure count climbing to `ALERT_AFTER_FAILURES`), plus an hourly heartbeat so the
  24 h TTL record never expires. A healthy origin now costs ~24 writes/day; an outage
  costs a few extra.
- Since `lastOk` is no longer refreshed every minute, the first failure after a stored
  `ok=true` sets `lastOk` to the previous tick (every probe since the last write was ok),
  so "last seen healthy" and the alert's down time stay accurate.
- `readStatus()` catches KV errors and returns the "never probed" default, which the
  fetch handler ignores — a KV failure can no longer block traffic. The `put` is guarded
  the same way.

## Verification

- `npx tsc --noEmit` in `infra/cloudflare/status-worker` is clean.
- After `npx wrangler deploy`: Cloudflare dashboard > Workers KV > metrics shows writes
  flat at ~1/hour while the origin is healthy; `origin-status` in KV still has a recent
  `lastChecked` (≤ 1 h).
