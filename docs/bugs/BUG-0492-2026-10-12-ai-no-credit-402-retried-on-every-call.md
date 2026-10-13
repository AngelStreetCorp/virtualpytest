# BUG-0492 — A model account with no credit (HTTP 402) was called again on every request

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0492                                                     |
| Reported  | 2026-10-12                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend / AI gateway / alert triage                          |
| Fixed in  | Unreleased                                                   |
| Commit    | `fa248686b`                                                  |

---

## Symptom

The AI usage page (TASK-87) showed `vision.alert_triage` at 117,141 calls and 117,120 errors in one day, and
`text.decision.localize` (Jev) failing 498 out of 498 times. The `ai_calls` log classified them as `no_credit`
(HTTP 402 from OpenRouter) and `other`.

`ai_usage_stats` by hour shows two separate problems:

- **Up to 2026-10-12 12:00 UTC**: about 9,000 failed `vision.alert_triage` calls per hour on `qwen3-vl-8b` (OpenRouter,
  402). That storm stopped when the TASK-84 worker back-off was deployed and the route moved to MiniMax VLM. The
  "last 24 h" figure still contained it.
- **Still live after that**: every Jev usage on OpenRouter (`text.decision.localize` from the `vpt-pi1` host,
  `text.decision.freeze_triage`, `text.decision.sherlock`) and `agent.browser` sent a request on each call and got a
  402 back each time, roughly 90 an hour. Alert triage itself failed about once per back-off window with "The MiniMax
  VLM endpoint needs an image": the same frameless alert retried for 6 h, and each failure blocked triage of every
  other alert.

## Root cause

- `gateway._execute_hops` and `decisions._decide` (`shared/src/lib/ai/`) treated a 402 like any HTTP error: count it,
  try the fallback, and call the same endpoint again on the next request. Only connection errors paused an endpoint
  (`router.mark_down`, 60 s). The back-off lived in only one caller, the Nightwatch worker. Every other caller, and
  every host process, kept calling the account.
- Nightwatch sent alerts with no uploaded frame (about 20 % of alerts over 3 days) to the vision route. MiniMax VLM
  refuses a text-only call. Each refusal started the worker's global back-off (60 s doubling to 1 h), and the same
  alert came back after every window.

## Fix

- `shared/src/lib/ai/router.py`: `router.record` sees each billed request. A `no_credit` result pauses that endpoint
  for every usage in the process: 120 s at first, doubling up to 1 h. While the pause runs, `gateway._execute_hops`
  and `decisions._decide` skip the endpoint without sending a request (the fallback answers, or the call fails at
  once with "no credit (HTTP 402), paused Ns more"). The first call after the pause is the probe. A 402 doubles the
  pause; an answer ends it ("has credit again").
- `backend_server/src/agent/core/nightwatch_handler.py`: new rule `no_frame`. An alert with no uploaded frame never
  goes to the vision model; it is marked `ai_strategy_skip` and kept for a human.
- Alerts page (TASK-84 goal 6): `alerts_db.get_triage_stats` returns `unavailable: {reason, since}` while the last
  triage request failed. `MonitoringIncidents.tsx` shows "Triage unavailable: no credit on the model account
  (HTTP 402) (last try HH:MM)" in red.
- Tests: `tests/shared/test_ai_gateway.py` (pause covers all usages, probe doubles the pause, recovery, fail-fast with
  no fallback) and `tests/shared/test_nightwatch_triage.py` (`no_frame`).

## Verification

After the deploy, count the failed calls for one hour:

```sql
SELECT usage_key, host_name, error_type, count(*) FROM ai_calls
WHERE NOT ok AND outcome = 'served' AND ts > now() - interval '1 hour' GROUP BY 1, 2, 3 ORDER BY 4 DESC;
```

Expected: a 402 usage shows a handful of rows per process (probes at 2, 4, 8, 16, 32 and 60 min), not one per
request. `vision.alert_triage` shows no "needs an image" failures. The server log for `vpt-discard-incidents` shows
`skip … no_frame` for frameless alerts.
