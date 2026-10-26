# BUG-0509 — Calls through the OpenAI passthrough had no team, user, host or script

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0509                                                     |
| Reported  | 2026-10-13                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                          |
| Area      | backend / AI gateway                                |
| Fixed in  | build 90145 |
| Commit    | `feat/ai-usage-r3`                                    |

---

## Symptom

The 160 `agent.browser` rows of BUG-0510 carried no team, user, host, script or client: nobody could tell who sent them (shown as "API (service key)").

## Root cause

`build_browser_llm` froze the `X-VPT-Caller` header into the client at build time, and `BrowserUseManager` cached that client for its whole life, so it named whoever happened to build it first, or nobody when built outside a request context. The passthrough also recorded nothing for a client that sends no header.

## Fix

`backend_host/src/lib/utils/browseruse_utils.py`: the LLM is rebuilt per task (header = current caller); with no caller bound the header names the host (`HOST_NAME`), `origin = background`, `job = agent.browser`. `backend_server/src/routes/server_ai_routing_routes.py`: a passthrough request whose caller names no user, host, script or session gets `client_hash` = sha256 of IP + User-Agent (12 hex), so an "Unknown API client" can be traced. Test: `tests/backend_server/test_ai_passthrough_pause.py`.

## Verification

`SELECT host_name, client_hash, count(*) FROM ai_calls WHERE usage_key='agent.browser' AND ts > now() - interval '1 day' GROUP BY 1,2` has a host or a client hash on every row.
