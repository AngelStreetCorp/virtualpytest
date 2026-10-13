# BUG-0177 — With a Claude model, every agent chat that loads a skill fails with a bare "400 Bad Request"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0177                                                     |
| Reported  | 2026-09-27                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High (for any non-MiniMax Claude setup)                      |
| Area      | backend_server agent manager / shared provider client        |
| Fixed in  | Unreleased                                                   |
| Commit    | aab2c4dfe                                                    |

---

## Symptom

This showed up after prod's agent was switched to `openrouter` with `anthropic/claude-sonnet-5`
for the promo recording. *Open YouTube in the browser, search for "Raspberry Pi"…* ended within
10 s with `AI service error: 400 Client Error: Bad Request for url:
https://openrouter.ai/api/v1/chat/completions` (session `5c7929ad`). A direct call with the same
key, model and tool definitions returned 200.

## Root cause

When the router answers in text with `LOAD SKILL <name>`, `process_message`
(`backend_server/src/agent/core/manager.py`) appends that assistant turn to the history, loads the
skill and calls the model again **with no user turn after it**. A request that ends on an
assistant message is an assistant *prefill*. MiniMax accepts it, but current Claude models reject
it with 400. The `tool_use` form of LOAD SKILL did not have the problem, because it answers with a
`tool_result` user turn.

The cause was hidden because `OpenAICompatibleProviderClient.create` called `raise_for_status()`,
which drops the response body where the provider explains the 400.

## Fix

- After a text LOAD SKILL, the manager appends the user turn `Skill '<name>' loaded. Continue with
  the user's request.`, the same as the `tool_use` path.
- The OpenAI-compatible client (OpenAI, OpenRouter, local) raises `HTTPError` with the first 500
  characters of the provider's response body.

## Verification

- `tests/backend_server/test_agent_minimax_quirks.py::test_load_skill_as_text_never_ends_request_on_assistant`
  fails before the fix and passes after it.
- On prod with Sonnet 5 via OpenRouter, the YouTube prompt loads a skill and completes.
