# BUG-0412 — A host's AI call crashed instead of failing cleanly when the server was unreachable

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0412                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low — only while the server is down or restarting            |
| Area      | `shared/src/lib/ai/gateway.py` (`_complete_remote`)          |
| Fixed in  | Unreleased                                                   |
| Commit    | this commit                                                  |

---

## Symptom

On a host, an AI call (`gateway.complete`) made while the server could not be reached raised
`UnboundLocalError: cannot access local variable 'data'` instead of returning
`{"success": false, "error": "AI gateway unreachable: …"}`. A connection refused while the server
restarts is enough to trigger it. Callers that rely on the result to back off saw an exception instead.
For example, the live-TV companion's step was aborted and logged as "step failed", and no back-off
started.

## Root cause

`_complete_remote` had two `except Exception` clauses in a row. The first one handled timeouts only.
The second was unreachable, so any other error fell through with `data` never set. Introduced with the
per-call timeout budget (`505602eac`, TASK-05).

## Fix

One `except` clause: a timeout within the call budget returns `busy`, and any other error returns
"AI gateway unreachable". Test:
`tests/shared/test_ai_web_search.py::test_host_call_with_the_server_down_returns_unreachable_not_a_crash`.

## Verification

The test fakes a refused connection with and without a call budget. Both return `success: false` with
"unreachable" and no exception.
