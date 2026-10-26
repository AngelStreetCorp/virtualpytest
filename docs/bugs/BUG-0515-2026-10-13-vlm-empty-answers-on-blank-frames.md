# BUG-0515 — MiniMax VLM alert triage sent the same blank frame three times an hour for nothing

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0515                                                     |
| Reported  | 2026-10-13                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend / AI gateway                                         |
| Fixed in  | build 90145 |
| Commit    | `fix/zero-wasted-ai`                                         |

---

## Symptom

111 `vision.alert_triage` calls on `minimax-vlm` ended `empty_answer` in 24 h: one alert an hour from vpt-pi4/device1 with a 741-753 byte frame, sent three times (attempt 0 and two retries) every hour. 6 `bad_request` rows (latency 0, 07:46-08:18 UTC) and 10 `other` rows (12 Oct 19:41-20:11, frameless alerts) were refused by our own client before a request left but were counted as served calls.

## Root cause

The frame is a flat image the VLM answers with nothing, every time; the gateway retried an empty answer twice on the same image (0 of 37 retries in 7 days ever produced an answer). Errors raised by our own client before any request (no image, no key) were logged as failed served calls. The `other` rows are fixed since the BUG-0492 deploy (no frameless alert is sent, ValueError classified `bad_request`).

## Fix

`gateway._call_hop`: no empty-answer retry on a `minimax_vlm` hop. `nightwatch_handler.classify`: a flat frame (`is_blank_frame`, brightest-darkest pixel < 6) is never sent - the alert is skipped `[SKIP:blank_frame]` and counted as an avoided call. `provider_client.RequestNotSent`: a call our client refuses before sending is recorded `outcome=skipped` (`stop_reason=not_sent`), not served. Tests: `tests/shared/test_ai_wasted_calls.py`.

## Verification

`SELECT error_type, count(*) FROM ai_calls WHERE endpoint='minimax-vlm' AND outcome='served' AND ts > now() - interval '24 hours' AND NOT ok GROUP BY 1` -> no `empty_answer` rows for flat frames, no `other`, no `bad_request`; skipped alerts carry `[SKIP:blank_frame]`. A non-flat frame the VLM still answers empty costs one call (was three) and the alert is given up after two (was six).

Report: `python3 scripts/ai_wasted_report.py --sql | <psql on the lab DB>` (TASK-93).
