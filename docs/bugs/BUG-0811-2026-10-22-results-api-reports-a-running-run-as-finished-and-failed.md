# BUG-0811 — While a run is in flight the results API publishes it as already finished and failed, with no duration and no reason

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0811                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Open                                                         |
| Severity  | Low                                                       |
| Area      | backend                                      |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding TESTER-08, in `docs/tasks/QA-TESTER-findings.md`); reproduced against the live app.

- **Page / route:** GET /server/script-results/getAllScriptResults
- **Viewport / theme:** n/a (API)

Steps to reproduce:

1. Start a run of about 45 seconds on labox-backend from the Run page.
2. Poll `GET /server/script-results/getAllScriptResults?team_id=<team>` every 4 s and watch that row.

**Expected:** No `completed_at` and no verdict while the run is in flight.

**Actual:** The row is created with `completed_at` equal to the start time, `execution_time_ms` null, `error_msg` null, `success` false, so it reads as an instant failure for the whole 46 s; it is corrected when the run ends. The Run page and Monitor Tests read another feed and show Running correctly, but any consumer of the API (CI check, report, the QA sweep itself) draws the wrong conclusion.

Evidence:

- [tester-11-monitor-shows-four-concurrent-runs.png](../tasks/qa-evidence/tester/tester-11-monitor-shows-four-concurrent-runs.png)

## Root cause

Not diagnosed yet: the QA sweep reported the symptom only.

## Fix

Not started.

## Verification

Repeat the steps above on the fixed build and confirm the expected behaviour, in the viewport and theme listed.
