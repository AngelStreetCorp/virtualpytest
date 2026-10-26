# BUG-0801 — The Test Reports "Success rate" and "Avg duration" tiles describe only the last 100 runs, with no period and no sample size

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0801                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Open                                                         |
| Severity  | Medium                                                       |
| Area      | frontend / backend                                      |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding ANALYST-A-01, in `docs/tasks/QA-ANALYST-findings.md`); reproduced against the live app.

- **Page / route:** /test-results/reports (Tests tab)
- **Viewport / theme:** 1440 px, dark and light; 390 px

Steps to reproduce:

1. Open `/test-results/reports`.
2. Read the tiles Success rate and Avg duration.
3. Compare with `GET /server/script-results/getAllScriptResults?limit=100` and `limit=1000`.

**Expected:** A stated period or sample size, or the same set the table shows.

**Actual:** The tiles match the newest 100 rows (71.0 % / 23.5 s); 300 rows give 81.3 % / 14.9 s; 1000 rows give 89.3 % / 29.5 s. The table is also capped at 100 with no pagination and no "showing 100 of N". A dashboard deep link (`?status=...&range=...`) switches the limit to 1000, so the number changes because of the URL, not the period. The server caps results at 1000. Monitoring > Analytics > KPI shows a different pass rate (82.6 %, 30 days) with no explanation.

Evidence:

- [reports.png](../tasks/qa-evidence/analyst/pass1/reports.png)
- [deep2-reports-bottom.png](../tasks/qa-evidence/analyst/deep2-reports-bottom.png)

## Root cause

Not diagnosed yet: the QA sweep reported the symptom only.

## Fix

Not started.

## Verification

Repeat the steps above on the fixed build and confirm the expected behaviour, in the viewport and theme listed.
