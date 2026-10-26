# BUG-0289 — Anthropic client creation fails on the new SDK (httpx.Timeout rejected)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0289                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | shared/src/lib/ai                                                |
| Fixed in  | build 90145 |
| Commit    | 39c0f6a8e                                                    |

---

## Symptom

`tests/shared/test_ai_web_search.py::test_anthropic_web_tool_and_answer_after_last_search` failed:
`TypeError: Invalid 'timeout' argument; httpx.Timeout is from the httpx package, but this SDK uses httpx2.`
On any install with `anthropic` 1.x every Anthropic-provider call (web search, vision, text) would fail when the
client is built. Production runs `anthropic` 0.58.2 and was not affected yet.

## Root cause

`AnthropicProviderClient.__init__` (`shared/src/lib/ai/provider_client.py`) passed `httpx.Timeout(...)`;
`backend_server/requirements.txt` pins only `anthropic>=0.40.0`, so a fresh install pulls the 1.x SDK, which
uses `httpx2` and rejects it.

## Fix

Build the timeout with `anthropic.Timeout(...)` (works on 0.x and 1.x); drop the unused `import httpx`.
