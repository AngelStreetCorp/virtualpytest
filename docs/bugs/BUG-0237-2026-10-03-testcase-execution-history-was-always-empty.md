# BUG-0237 — A test case's execution history was always empty

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0237                                                     |
| Reported  | 2026-10-03                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low — the history list of a test case showed no runs; the runs themselves and their reports were intact |
| Area      | `shared/src/lib/database/testcase_db.py` (`get_testcase_execution_history`), served by `/host/testcase/<id>/history` via `/server/testcase/<id>/history` |
| Fixed in  | build 90145 |
| Commit    | `961a0769d`                                                  |

---

## Symptom

`GET /server/testcase/<id>/history` answered with an empty list for every test case, including
ones that had run many times and whose results were visible in Test Reports.

## Root cause

The query selected a `script_result_id` column. `script_results` has no such column — its key
is `id`. PostgREST rejected the select, and the function's `except` turned the error into an
empty list, so the failure looked like "no runs yet". The bug dates from the first snapshot of
the code.

## Fix

Select `id` (plus `discard`) and return it under the `script_result_id` key the callers already
read. No caller changes.

## Verification

- Found while building TASK-42 (test run management), whose testcase Versions panel links to a
  test case's recent results; both the UI worker and the core worker independently traced the
  column against `setup/db/schema/003_test_execution_tables.sql`.
- `py_compile` passes. Live verification needs a deploy (the route reads the shared database).
