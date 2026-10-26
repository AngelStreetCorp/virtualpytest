# BUG-0790 — After a page reload the Run page's Abort button is disabled although its own table shows the run still running

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0790                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Open                                                         |
| Severity  | Medium                                                       |
| Area      | frontend                                      |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding OPS-20, in `docs/tasks/QA-OPS-findings.md`); reproduced against the live app.

- **Page / route:** /test-execution/run-tests
- **Viewport / theme:** 1440 px, dark

Steps to reproduce:

1. Start a run from the Run page.
2. While it is running, reload the page.
3. Compare the Abort button with the Last Executions table.

**Expected:** Abort is available while a run shows Running.

**Actual:** Abort is disabled while the table row reads `labox-backend | web/browser_task.py | 2 min ago | - | - | Running`. Only the small unlabelled stop icon in the row's Action column can stop it. The same applies to a run started by another operator.

Evidence:

- [ops-20-abort-disabled-while-running.png](../tasks/qa-evidence/ops/ops-20-abort-disabled-while-running.png)

## Root cause

The table merges server history with local runs (`RunTests.tsx:3736-3762`); Abort is driven by `runningTargetKeys` built only from the in-memory `activeExecutions` of this browser session (`:406-417`, `:4112`).

## Fix

Not started.

## Verification

Repeat the steps above on the fixed build and confirm the expected behaviour, in the viewport and theme listed.
