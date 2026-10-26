# BUG-0516 — An unreachable LM Studio endpoint was called again on every request

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0516                                                     |
| Reported  | 2026-10-13                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend / AI gateway                                         |
| Fixed in  | build 90145 |
| Commit    | `fix/zero-wasted-ai`                                         |

---

## Symptom

`lmstudio-pc` / `text.game_2048`: three `connection` failures in 15 s (5 s timeout each) from vpt-pi1.

## Root cause

A connection failure marks the endpoint down for 60 s, but the resolver only moved it behind healthy hops ("if everything is down the call still tries"); with no fallback every call went out and waited for the timeout.

## Fix

`router.skip_down`: the gateway does not call an endpoint whose down-wait is running (recorded `outcome=skipped`, `error_type=connection`, `stop_reason=endpoint_down`); the next call after 60 s is the probe. Test: `tests/shared/test_ai_wasted_calls.py::test_unreachable_endpoint_is_not_called_until_its_wait_is_over`.

## Verification

`SELECT count(*) FROM ai_calls WHERE error_type='connection' AND outcome='served' AND ts > now() - interval '24 hours'` stays at one per outage per minute.

Report: `python3 scripts/ai_wasted_report.py --sql | <psql on the lab DB>` (TASK-93).
