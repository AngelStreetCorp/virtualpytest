# BUG-0323 — Atlas silently substituted other devices for ones that do not exist

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                      |
|-----------|--------------------------------------------|
| ID        | BUG-0323                                     |
| Reported  | 2026-10-04                                 |
| Status    | Fixed (pending deploy)                     |
| Severity  | Medium — a canvas titled after devices the user never named         |
| Area      | backend_server/src/lib/analytics/service.py |
| Fixed in  | build 90145 |
| Commit    | see branch task43-w7-analytics-r3           |

---

## Symptom

Asked for devices samsung SM-G998B and Phone slot 1 (not on the server), the model mapped them to S21x/stb3 and titled the canvas after those.

## Root cause

An empty/partial result for a device_name filter only said generic 'NO DATA matched'.

## Fix

Device/host filter values that match no row are reported (`unmatched_filters`, kept in the artifact options with the applied filters) and the tool reply says '<field> <value> matched nothing on this server - tell the user; do not substitute other devices or drop the filter'. If the model itself drops the filter, no reply text can show it; that stays a prompt matter.

## Verification

`python3 -m pytest -q tests/backend_server -k "atlas or minimax or analytics or agent"` (`test_unmatched_device_filter_is_reported_to_the_model` in `tests/backend_server/test_atlas_analytics.py`).
