# BUG-0275 — One slow status read ended execute_testcase while the testcase ran on

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0275                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — the caller started the next testcase on a busy device |
| Area      | `backend_server/src/mcp/tools/testcase_tools.py` (`_poll_testcase_completion`) |
| Fixed in  | Unreleased                                                   |
| Commit    | `this commit`                                                |

---

## Symptom

MCP `execute_testcase` answered `❌ Status check failed: Request timeout (30s)` for a testcase
that was still running on the host (QualiAi stb4 run, 2026-10-03, `02_open_tvguide_from_home`).
The caller took it as "failed to launch" and started the next testcase on the same device.

## Root cause

The poll ended on any unsuccessful status read. The MCP API client gives each request 30 s; a
status read slower than that (a loaded host or server) returned `{'success': False, 'timeout':
True}` and the poll returned it as the run's failure. The poll's `elapsed` also counted only the
sleeps, not the time spent in the reads.

## Fix

A status read that timed out, failed on the network or got a 5xx is read again while the run's
own wait lasts; other errors (an execution VPT does not know) still end the poll. `elapsed` is
wall time.

## Verification

`tests/backend_server/test_mcp_execution_status.py` (the poll became get_testcase_execution_status in BUG-0378), with a control: a 404
still ends the poll.
