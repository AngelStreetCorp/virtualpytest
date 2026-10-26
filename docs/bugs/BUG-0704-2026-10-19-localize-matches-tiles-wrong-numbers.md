# BUG-0704 — Localize Matches tab showed an average confidence of 0.00 and wrong per-device rates

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0704                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend Localize page, shared match_runs_db                 |
| Fixed in  | build 90145 |
| Commit    | 9522478bb                                                    |

---

## Symptom

Found by the five-user review of `/monitoring/localize` ([TASK-137](../tasks/TASK-137-localize-page-ux.md)), node1, 24 h window:
- "Avg confidence 0.00 · matched only" while the same window had 74 matched runs scoring around 0.82.
- The per-device squares' tooltip said "53/128 matched (60.0%)" on a row labelled 41.4 %.
- "Uncertain (margin < 5%) 6.8 %" in green beside red tiles; 5 of 343 runs is 1.5 %, the tile was 5 of 74 matched, unlabelled.

## Root cause

- `MatchRuns.tsx` summed `matched_confidence` over the short `recent` list but divided by `summary.matched` (the whole
  window). When `recent` held no matched run, the average was 0.
- `HeatCell` received the shading value (`max(rate, 0.6)` / `min(rate, 0.4)`) as its rate and printed it in the tooltip.
- The Uncertain tile divided by matched runs while its neighbours divided by all runs, and took the success colour scale.

## Fix

- `shared/src/lib/database/match_runs_db.py` `summary()` returns `avg_confidence` over the window's matched runs; the tile reads it.
- `HeatCell` takes the real rate for its tooltip and a separate `shade` for the colour.
- The tile is "Close calls", "x of y matched", amber when above 0.

## Verify

Live page, 24 h: the average score tile is non-zero when matched > 0; a device's square tooltip equals its row's percentage.
