# BUG-0312 — Analytics 'Unsupported fields' error did not say which fields are valid

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                      |
|-----------|--------------------------------------------|
| ID        | BUG-0312                                     |
| Reported  | 2026-10-04                                 |
| Status    | Fixed (pending deploy)                     |
| Severity  | Low — one wasted failing tool call         |
| Area      | backend_server/src/lib/analytics/service.py |
| Fixed in  | build 90145 |
| Commit    | see branch task43-w5-scope-hints           |

---

## Symptom

The model guessed field names (pass_rate, run_count, device_id) and got only Unsupported fields: [...], then spent 2-4 describe/query calls finding valid ones.

## Root cause

compile() reported the bad names only.

## Fix

The error now adds a close-match suggestion per bad field (difflib) and the source's valid dimensions and metrics (capped at 25 each), so one retry suffices.

## Verification

`python3 -m pytest -q tests/backend_server -k "atlas or minimax or analytics or agent"` (regression tests added in
`test_agent_minimax_quirks.py` / `test_atlas_analytics.py`).
