# BUG-0322 — Analytics unknown/empty source id error listed nothing

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                      |
|-----------|--------------------------------------------|
| ID        | BUG-0322                                     |
| Reported  | 2026-10-04                                 |
| Status    | Fixed (pending deploy)                     |
| Severity  | Low — extra model calls         |
| Area      | backend_server/src/lib/analytics/service.py |
| Fixed in  | build 90145 |
| Commit    | see branch task43-w7-analytics-r3           |

---

## Symptom

'Unknown analytics source: ' (empty) cost the model extra calls; a canvas gave no hint which panel lacked source_id.

## Root cause

_source() reported the bad id only; canvas errors had no panel context.

## Fix

The error lists valid source ids and close matches (difflib); canvas panel errors are prefixed with 'Panel N <title>'.

## Verification

`python3 -m pytest -q tests/backend_server -k "atlas or minimax or analytics or agent"` (`test_unknown_or_empty_source_lists_valid_ids_and_close_matches / test_canvas_panel_errors_name_the_panel` in `tests/backend_server/test_atlas_analytics.py`).
