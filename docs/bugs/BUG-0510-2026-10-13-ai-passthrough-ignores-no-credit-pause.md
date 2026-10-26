# BUG-0510 — The OpenAI passthrough ignored the AI no-credit pause: 160 failing browser-agent calls overnight

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0510                                                     |
| Reported  | 2026-10-13                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                          |
| Area      | backend / AI gateway                                |
| Fixed in  | build 90145 |
| Commit    | `feat/ai-usage-r3`                                    |

---

## Symptom

`ai_calls` showed 160 `agent.browser` calls between 19:52 and 11:37, in bursts of 5 every ~15 minutes, all HTTP 402 (no credit). The pause of BUG-0492/0497 was active for the endpoint.

## Root cause

`/server/ai/openai/<usage>/chat/completions` (`_passthrough_hops`) sent every request to the provider; only `gateway` consulted `router.no_credit_error`.

## Fix

`backend_server/src/routes/server_ai_routing_routes.py`: each hop is checked with `router.no_credit_error` first. A paused hop is not called; it is recorded once as `outcome = skipped`, `error_type = no_credit`, `stop_reason = provider_paused`. When every hop is paused the client gets an OpenAI-shaped HTTP 402 (`insufficient_quota`) locally. Test: `tests/backend_server/test_ai_passthrough_pause.py`.

## Verification

While an endpoint has no credit: `SELECT count(*) FROM ai_calls WHERE usage_key='agent.browser' AND outcome='served' AND error_type='no_credit' AND ts > now() - interval '1 hour'` stays at the one call that started the pause; skipped rows carry `stop_reason = provider_paused`.
