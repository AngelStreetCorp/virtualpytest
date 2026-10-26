# BUG-0514 — Calls to an AI account without credit still left after the pause: one probe per process per burst, and a CI browser task that retried five times

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0514                                                     |
| Reported  | 2026-10-13                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend / AI gateway                                         |
| Fixed in  | build 90145 |
| Commit    | `fix/zero-wasted-ai`                                         |

---

## Symptom

After the BUG-0510 deploy (~13:10 UTC) `agent.browser`, `text.decision.sherlock` and `freeze_triage` still sent HTTP 402 requests to OpenRouter: 1-2 `served` rows per hour (13:15, 14:04, 15:22, 15:33 and a sherlock row at 14:16 while the pause was active). The `agent.browser` rows come from one client (`client_hash 6489e99c717b`, origin `background`): the CI web smoke (`regression.yml` -> `test_scripts/web/browser_task.py` -> browser-use against the lab server), which fires on every push to main, five model calls per task (`max_failures=5`).

## Root cause

1. The expired-pause probe was not claimed: every caller that found the wait over passed, so a burst or a second process each sent its own 402. When the free credit check said "credit available" (the balance can read positive while calls still 402) the pause was erased and the back-off restarted at 5 min, so the same probe repeated every ~15 min.
2. The pause lived in each process (server, discard worker, monitor): each one had to learn it with its own paid 402 (sherlock runs in another process than the passthrough).
3. The CI browser task did not look at availability before starting and browser-use retried the refused step five times; the Settings test buttons and the agent tool loop (`agent.*`) did not look at the pause at all.

## Fix

`shared/src/lib/ai/router.py`: the probe is claimed atomically (the pause is re-armed for the same back-off before the call leaves; only a 402 grows it, only an answer ends it - a positive balance no longer erases the back-off); the pause is shared by all processes of a machine through `$TMPDIR/vpt_ai_no_credit.json` (`VPT_AI_PAUSE_FILE`). `/server/ai/resolve` reports `available: false` + `paused` while every hop is paused; `BrowserUseManager.execute_task` asks before starting and a 402 stops the agent at the first refusal (`browseruse_utils.py`); Settings tests (`_counted_test`) and the agent tool loop (`manager._create_turn`) skip a paused endpoint without a request. Tests: `tests/shared/test_ai_wasted_calls.py`, `tests/backend_server/test_ai_wasted_routes.py`, `tests/backend_host/test_browseruse_no_credit.py`.

## Verification

After deploy, with the account still without credit: `SELECT usage_key, count(*) FROM ai_calls WHERE endpoint='openrouter' AND outcome='served' AND error_type='no_credit' AND ts > now() - interval '24 hours' GROUP BY 1` shows at most the probes of the 5 min / 15 min / 1 h steps (about 1 per hour in total, not per process or per task); CI browser task fails with "agent.browser is not available now" and no `agent.browser` row. Remaining cause that cannot be avoided: the probe itself (one call per hour while the balance is unreadable or reads positive).

Report: `python3 scripts/ai_wasted_report.py --sql | <psql on the lab DB>` (TASK-93).
