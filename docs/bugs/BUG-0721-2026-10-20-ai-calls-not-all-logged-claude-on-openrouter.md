# BUG-0721 — Some AI calls were not logged, and Claude ran through OpenRouter

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0721                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | ai / backend_server / scripts / db                           |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

The owner saw OpenRouter money going faster than expected and could not see what used it. On Monitoring → AI usage,
`agent.browser` (o4-mini on OpenRouter) showed dozens of calls with 0 tokens and $0 cost, and other spend did not
appear at all.

## Root cause

Four separate problems:

1. **The zero-token rows were refused calls.** In 48 h, `agent.browser` logged 895 calls through the OpenAI
   passthrough from one unnamed API client (`client_hash 6489e99c717b`, origin `background`). 1249 of the 7-day rows
   were HTTP 400 answers returned in about 70 ms. OpenRouter bills nothing for a 400 and sends no usage. The calls
   that were answered did log tokens and cost. The passthrough did not log why the provider refused, so a row with
   0 tokens looked like unlogged spend.
2. **The OpenRouter spend was Claude.** On 2026-10-19 Forge's build-tree-web skill ran on the
   `openrouter-claude-sonnet-5-5` and `openrouter-claude-haiku-5-5` profiles: $7.87 of that week's $8.38 on the
   OpenRouter key. ai_calls did record it.
3. **Some paths never wrote to ai_calls:**
   - the agent API-key check (`POST /server/agent/api-key`, a real completion);
   - six scripts that call a provider themselves: the Localize model bench, the LoL LLM relay, the LoL game review
     (Anthropic backend), the CoC LLM player, the promo voice-over (MiniMax TTS) and two `claude -p` runs.
4. **Rows could be lost:**
   - a failed voice command recorded `error_type="http"`, which the ai_calls CHECK constraint rejects, so the whole
     batch of up to 100 rows failed;
   - scripts could exit before the logging thread wrote their last rows;
   - `ai_calls_ingest` never wrote `project_id`;
   - the fallback chain stopped at the first disabled hop instead of stepping over it.

The usage parser also knew only the Chat Completions names (`prompt_tokens` / `completion_tokens`). A Responses API
usage block (`input_tokens` / `output_tokens`) would have counted as 0.

## Fix

- Passthrough: a provider 4xx is logged with its body.
- `openai_call_usage` reads the Responses API names too. `anthropic_call_usage` reads raw Messages usage.
- `call_log`: an unknown `error_type` becomes `other`, and the queue is flushed at process exit. The voice command
  sends `other`.
- The API-key check is counted as `test:text`.
- `gateway.report_external_call` sends a script's call to `POST /server/ai/stats` with origin `script`. The six
  scripts use it. `scripts/ai_report_claude_cli.py` logs `claude -p` JSON results.
- Guard `tests/shared/test_ai_call_guard.py` fails on any unlisted direct provider call.
- `scripts/ai_calls_audit.py` lists ok rows with 0 tokens on endpoints that bill tokens, and exits 1 if it finds any.
- Claude chain (owner rule 2026-10-20). Every Claude profile now runs AngelStreet key → Individual key (endpoint
  `anthropic-individual`, user key plus `anthropic-workspace-id` header) → MiniMax M3. A disabled hop is stepped
  over. `router.claude_off_anthropic` keeps Claude off every non-Anthropic endpoint, and Settings refuses such a
  profile. The OpenRouter Claude profiles are disabled.
- Migrations:
  - `20261020b_ai_calls_hop_index.sql`: `ai_calls.hop_index`, and the RPC writes `project_id`;
  - `20261020c_claude_anthropic_chain.sql`: endpoint, twin profiles, chain.

  Both are applied on the lab DB.

## Verification

- `pytest tests/shared/test_ai_claude_chain.py tests/shared/test_ai_call_guard.py`
- On the server, `python3 scripts/ai_calls_audit.py` prints OK.
- Live proof: one call per provider and per chain hop, each with non-zero tokens and a cost or price-table row, and
  `hop_index` / `fallback_used` set (see the release note).
- `GET https://openrouter.ai/api/v1/key`: `usage_daily` matches `sum(cost)` of today's `openrouter` rows within 1 %.
