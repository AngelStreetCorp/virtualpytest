# BUG-0793 — The Run page starts a script whose required parameter is missing, so the run burns a browser slot and fails on its own argument check

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0793                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Open                                                         |
| Severity  | Medium                                                       |
| Area      | frontend                                      |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding TESTER-10, in `docs/tasks/QA-TESTER-findings.md`); reproduced against the live app.

- **Page / route:** /run/tests
- **Viewport / theme:** 1440 px, dark

Steps to reproduce:

1. Pick a target and the script "Netflix Video Check".
2. Press Run without filling the script's parameters.
3. Read the result row.

**Expected:** The page refuses to start or asks for the missing field.

**Actual:** The run starts and fails after 1.9 s with `Missing required --email`. It took a browser slot and tells the user nothing at the point where it could still be fixed, although the page has a parameter panel and knows the value is missing.

Evidence:

- [tester-11-monitor-shows-four-concurrent-runs.png](../tasks/qa-evidence/tester/tester-11-monitor-shows-four-concurrent-runs.png)

## Root cause

Not diagnosed yet: the QA sweep reported the symptom only.

## Fix

Not started.

## Verification

Repeat the steps above on the fixed build and confirm the expected behaviour, in the viewport and theme listed.
