# BUG-0831 — Caption translation burns paid OpenRouter calls that come back empty

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0831                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend / ai (gateway, router, usages)                       |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Dashboard: "$1.59 of $2.19 AI spend wasted today (73 %)". `ai_usage.waste.top`: `process:vpt-monitor` $1.59 (1.6 M tokens),
all of it usage "Caption translation". The newest 200 calls (13 min, ~15 calls/min): 141 OpenRouter `minimax/minimax-m3`
`empty_answer` (billed, ~2.4k tokens, $0.0017 to $0.0025 each, `stop_reason = max_tokens`, 1998-1999 of 2000 output tokens
were reasoning) and 59 native `minimax-m3` `rate_limit` (free). About $1.5 per hour while MiniMax stays rate limited.

## Root cause

- Fallback: the Caption translation route (`text` root) is profile `minimax-m3` with the paid `openrouter-minimax-m3` as
  fallback profile. `gateway._execute_hops` (shared/src/lib/ai/gateway.py) treats a 429 like any hop error and moves to the
  next hop, so a rate limit on the flat-rate endpoint always led to a paid hop.
- Empty answer: `provider_client` OpenAI-compatible request sends `max_tokens = 2000` (caption_translate.MAX_TOKENS)
  and nothing about reasoning; M3 on OpenRouter reasons first and spends the whole budget, so the answer is empty
  (`gateway._call_hop` then retries `EMPTY_RETRIES = 2`, each retry billed, and `caption_translate` asks again,
  `MAX_ATTEMPTS = 2`, `MAX_MINUTE_TRIES = 3`). Only calls whose reasoning stopped early (about 12 of 200) answered.
- Volume: one call per transcribed minute and target language; the per-minute result is already cached on disk
  (`translated_minutes` in `chunk_10min_<n>_<lang>.json`), so a minute is never re-sent once translated, but a failing
  minute is retried 3 times over time, times 3 attempts times 3 hops, times every device and language.

## Fix

- `usages.BEST_EFFORT` (`text.caption_translation`): `router.skip_after_rate_limit` skips the fallback hop after a 429
  (recorded `skipped`, `stop_reason = rate_limited_no_paid_fallback`); the caller keeps the source text.
- Empty-answer circuit breaker (`router.note_empty` / `breaker_open_for` / `skip_breaker`): 3 empty billed answers in a row
  on an endpoint open it for 15 min for that usage, shared by all processes through a file (`VPT_AI_BREAKER_FILE`);
  retries stop at once; after the wait one probe goes out, one more empty re-opens.
- OpenRouter hops of a best-effort usage send `reasoning: {"enabled": false}` (`Hop.extra_body`).

## Verification

`pytest tests/shared/test_ai_best_effort.py` (5 of 8 fail on the old code). After the server deploy: calls per minute of
`text.caption_translation`, share of `empty_answer`, and cost per minute from `GET /server/ai/usage/calls`.
