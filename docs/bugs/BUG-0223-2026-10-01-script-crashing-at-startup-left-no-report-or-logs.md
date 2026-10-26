# BUG-0223 — A script that crashed at startup left an empty run: no report, no logs, nothing to debug

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                             |
|-----------|-------------------------------------------------------------------|
| ID        | BUG-0223                                                          |
| Reported  | 2026-10-01                                                        |
| Severity  | Medium — the run fails with no evidence; the cause is only in the host's journal |
| Status    | Fixed (pending deploy)                                            |
| Area      | `shared/src/lib/executors/script_executor.py`                     |
| Fixed in  | build 90145 |
| Commit    | this commit                                                       |

---

## Symptom

A stray character typed at the top of a test script (a lone `a` above the shebang). The
run fails, but its row has no report and no logs, so there is no way to see why from the
UI.

## Cause

Reports, logs and the `script_results` row are all produced inside the script process by
the `@script` decorator. A script that dies before the decorator runs — a syntax error,
a failing import, a `NameError` at module level — exits 1 having printed only a Python
traceback. The host captured that output and returned it with `exit_code: 1`, but no
`SCRIPT_SUCCESS`, no `SCRIPT_RESULT_ID` and no report or logs URL, so nothing was ever
uploaded or recorded.

## Fix

`ScriptExecutor` (host side, every launch path: Run Tests, API, deployments) now detects
that case — exit code > 0 with neither marker — and builds the artifacts itself from the
captured output:

- an error naming the cause: "Script crashed before it started (exit code 1) — the file
  is likely corrupted or has a syntax/import error: NameError: name 'a' is not defined"
  (the last traceback line);
- a report and a log (the full output, traceback included), uploaded like any run's;
- a failed `script_results` row carrying both, returned as `script_result_id`, so the
  run's row links them.

A killed run (abort or timeout: negative exit code) is left alone.

## Verification

Offline, with the upload and DB calls stubbed, against real child processes:

| script | error recorded |
|---|---|
| a lone `a` above the shebang | `NameError: name 'a' is not defined` |
| `from os import nothing_here` | `ImportError: cannot import name 'nothing_here' from 'os' …` |

Both returned `script_success: False`, the report/logs URLs and the new
`script_result_id`, with the traceback in the uploaded log. Not yet run on a host.
