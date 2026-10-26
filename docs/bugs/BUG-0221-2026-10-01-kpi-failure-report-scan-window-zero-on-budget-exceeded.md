# BUG-0221 — A KPI failure report for "scan budget exceeded" showed a 0.00 s scan window and no frames

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0221                                                     |
| Reported  | 2026-10-01                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low — the measurement result was right; the report could not be read |
| Area      | `backend_host/scripts/kpi_executor.py`, KPI failure report   |
| Fixed in  | build 90145 |
| Commit    | this commit                                                  |

---

## Symptom

A KPI Measurement Failed report said `scan budget exceeded (30s)` in its header, but its
Failure Details showed **Scan Window 0.00s**, the scan start / middle / end thumbnails and the
mosaic were missing, and Scan End was `N/A`. The two numbers looked contradictory.

## Root cause

They are different things: the budget is how long the host may spend *processing* the scan
(30 s wall clock), the scan window is how much *video* the scan covered. When the budget ran
out, `_process_measurement_inner` built the failure result with `'all_captures': []` — the
frame list lived inside the cancelled `_scan_until_match` — so the report computed the window
from an empty list (0.00 s) and had no frames to show.

A second, smaller defect sat in the same evidence: the image `image_filter` was read from
`imageFilter`, a key only the HTTP routes add, so KPI evidence always said `none`.

## Fix

- `_scan_until_match` publishes the frame list into the shared `progress` dict as soon as it is
  found; the deadline path uses it, so the report shows the real window, strip and mosaic.
- The error now reads `scan budget exceeded (30s of processing, N of M frames verified)`.
- `verification_executor.py` reads `image_filter` from the controller result.

## Verification

Rendered the failure template and a verification card locally with the new fields; mock-ran the
greyscale retry. Not yet checked on a deployed host.
