# BUG-0486 — Billed AI calls missing from the usage stats (compaction, public Ask, MCP prompt, browser-use, Test buttons, retries)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0486                                                     |
| Reported  | 2026-10-12                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | shared · ai · usage stats                                    |
| Fixed in  | build 90145 |
| Commit    | `ee7dde051`                                                      |

---

## Symptom

`ai_usage_stats` (Settings → AI 24 h numbers, agent dashboard) under-counted what the providers billed.
Found by the TASK-87 coverage review (§5.1): `public.ask` and `agent.mcp_prompt` never appeared, a
chat's history compaction was invisible, browser-use calls on a host-reach endpoint were not counted,
the Settings Test buttons were billed but not recorded, and an empty answer that was retried (up to 3×
on one hop) counted as a single call with the last attempt's tokens. A hop skipped because its endpoint
was saturated left no trace at all. Cache-read / cache-write tokens, reasoning tokens, web searches
and the provider-reported cost were thrown away, so agent cost would have been overstated.

## Root cause

`router.record` was called only from the gateway (one record per hop, not per request), the agent turn
loop and the OpenAI passthrough. Every other call site built its own client (`tracing.traced_create`,
`client.messages.create`, browser-use's `ChatOpenAI`) and only traced to Langfuse, and
`provider_client.response_tokens` returned `(input, output)` only.

## Fix

- `provider_client.response_usage()` returns tokens + cache read/write + reasoning + web searches +
  provider cost (OpenRouter is asked for `usage.cost`); `response_tokens` stays `(in, out)`.
  `classify_error()` maps an exception to the fixed `error_type` list.
- `gateway._call_hop` reports every billed attempt, so each empty-answer retry is counted; refusals keep
  their tokens; a saturated hop is recorded as a failed hop (`busy`).
- `tracing.traced_create(resolution=…)` counts the request: used by public Ask and the MCP prompt tool.
- The agent manager counts the history-compaction call and passes full usage for every turn.
- Settings Test buttons record as `test:<kind>`; the browser-use host path reports each model call to
  `/server/ai/stats` through `gateway.report_direct_call`; Jev's own cost is kept.

## Verification

`pytest tests/shared/test_ai_usage_counting.py` — empty retries count 4 requests with attempt indexes,
errors classified, refusal tokens kept, busy recorded, usage parsing for both response shapes, provider
cost kept, `traced_create` counts only when given a resolution.
