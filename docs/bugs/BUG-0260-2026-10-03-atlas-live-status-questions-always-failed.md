# BUG-0260 — Atlas answered every live server/host/device status question with "Analytics query failed"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0260                                                     |
| Reported  | 2026-10-03                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — the live-status half of Atlas analytics never returned data |
| Area      | `backend_server/src/lib/analytics/service.py` (live status adapter) |
| Fixed in  | Unreleased                                                   |
| Commit    | `8ee5bd2bc`                                                       |

---

## Symptom

Asking Atlas for current status ("which devices are offline right now?") through
`query_analytics_data(source_id='live_system_status')` always returned the generic
*Analytics query failed.* error, for every role and filter.

## Root cause

`AnalyticsService._live_status()` built its result with `source.id`, but `source` was a
local of the caller (`query()`), not of `_live_status()`. Every call raised `NameError`
after the registry had been read, and the MCP layer masked it as a generic failure (it never
returns driver/exception text to the model).

## Fix

The source is passed to the adapter explicitly, and the live result now always carries the
source's declared fields (an empty result no longer has an empty field list).

## Verification

- `tests/backend_server/test_atlas_analytics.py::test_live_status_uses_registry_with_device_ceiling`
  drives the adapter with a fake registry: filters, the device ceiling for a non-admin and the
  missing-adapter error.
