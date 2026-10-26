# BUG-0215 — Test Prompt "Save as testcase" created the testcase but never linked it

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0215                                                     |
| Reported  | 2026-10-01                                                   |
| Status    | Fixed — deployed and verified 2026-10-01                     |
| Severity  | Medium — Run graph never replays a saved testcase: every run regenerates (an AI call) and each save adds another testcase |
| Area      | `features/ai-test/backend_server/server_testprompt_routes.py`, `backend_host/src/routes/host_testcase_routes.py` |
| Fixed in  | build 90145 |
| Commit    | this commit                                                  |

---

## Symptom

First real-device check of TASK-36 (host-clone-1 / `host`, `sauce-demo`, prompt `2142fd59`).
After a passing Run graph, `POST /server/testprompt/<id>/save-testcase` created testcase
`f38ad30c` and then answered `{"success": false, "test_prompt": null, "testcase_id": {…}}`. The
prompt's `testcase_id` stayed empty, so the next Run graph generated the graph again.

## Root cause

`shared/src/lib/database/testcase_db.create_testcase` returns
`{testcase_id, testcase_name, success}` when it inserts a row. On its other paths it returns a
plain id or a marker string (`VALIDATION_FAILED`, `DUPLICATE_NAME`). Only
`/server/testcase/save` unwrapped the dict. Three callers used it as the id:

- Test Prompt `save-testcase` passed the dict to `link_testcase`, so the update matched nothing.
- Host `POST /host/testcase/save` (create path) returned the dict as `testcase_id`.
- Host `execute-from-prompt` with `save_testcase` returned the dict as `testcase_id`.

The mocked tests for TASK-36 had `create_testcase` return a string, so they could not catch it.

## Fix

The three callers take `testcase_id` out of the dict when one comes back.

## Verification

- `py_compile` on both files.
- After the full deploy of `89602040d` (2026-10-01) on host-clone-1: Run graph with
  `regenerate: true` passed (`773168f4`). Save as testcase returned `success: true` with testcase
  `7c14373d`, and the prompt's `testcase_id` is `7c14373d`. The next Run graph replayed it
  ("Running the linked testcase") and passed (`96fa4671`).
