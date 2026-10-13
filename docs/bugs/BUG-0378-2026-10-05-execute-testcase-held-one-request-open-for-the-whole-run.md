# BUG-0378 — execute_testcase and execute_script held one request open for the whole run, so a proxy answered 524

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0378                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High — an MCP client behind a proxy could not run a testcase longer than the proxy's limit |
| Area      | `backend_server/src/mcp/tools/testcase_tools.py`, `script_tools.py` (MCP) |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

An MCP client calling `execute_testcase` through a proxy (Cloudflare) got `HTTP 524` for any
testcase that ran longer than about 100 s. The testcase went on running on the host; the client
had no execution_id to follow it with. `execute_script` had the same failure for long scripts.

## Root cause

`execute_testcase` started the run, then polled `/server/testcase/execution/<id>/status` inside
the same MCP request for up to 300 s (`_poll_testcase_completion`); `execute_script` polled for up
to 7200 s (`_poll_script_completion`). The proxy closes a request that sends nothing for 100 s.
The poll's failure branch also called an undefined `_publish_execution_event` / `TriggerType`,
so a testcase that ended in `failed` raised a NameError.

## Fix

- `execute_testcase` / `execute_testcase_by_id` / `execute_script` return the `execution_id` at
  once (`structuredContent.status = running`).
- New tools `get_testcase_execution_status` and `get_script_execution_status` read the run. Each
  call waits up to `wait_seconds` (default 20, max 50) and answers with
  `{status, done, passed, report_url, logs_url, ...}`. A status read that timed out or got a 5xx
  answers `unknown, done: false` (read again), not a failure (keeps BUG-0275's fix).
- Shared code in `backend_server/src/mcp/utils/execution_status_*.py`; the poll loops are gone.
- MCP docs (`docs/mcp/`), generated definitions and the agent's testcase/script skills updated.

## Verification

`tests/backend_server/test_mcp_execution_status.py`: execute returns the id with no status read;
the status tools wait for the end, stop at `wait_seconds`, cap it at 50, treat a slow read as
`unknown`, and still end on a 404.
