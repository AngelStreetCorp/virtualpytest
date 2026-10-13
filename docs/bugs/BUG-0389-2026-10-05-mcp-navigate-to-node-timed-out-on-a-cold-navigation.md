# BUG-0389 — MCP navigate_to_node timed out on a cold navigation that then finished

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0389                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Closed                                                       |
| Severity  | Medium                                                       |
| Area      | backend_server / MCP                                         |
| Fixed in  | Unreleased |
| Commit    | TBD                                                          |

---

## Symptom

On host-clone-1 (youtube-web), the first `navigate_to_node` call after a cold start answered
`Navigation failed: Request timeout (30s)`. The navigation took 20–93 s and kept running; calling
the tool again answered "Already at target".

## Root cause

`navigate_to_node` (`backend_server/src/mcp/tools/navigation_tools.py`) POSTs to
`/server/navigation/execute/<tree_id>` through `MCPAPIClient.post()`, whose timeout is a fixed
30 s. That route answers only when the navigation is over: it checks the host's navigation cache
(5 s), populates it when missing (`call_host` default 30 s), checks again (5 s), then proxies
`/host/navigation/execute` with a 120 s timeout — web devices run the navigation synchronously.
A cold navigation therefore routinely needs more than 30 s, and the MCP client gave up while the
server and host carried on.

## Fix

- `backend_server/src/mcp/utils/api_client.py` — `post()` takes an optional per-call `timeout`
  (default unchanged at 30 s).
- `backend_server/src/mcp/tools/navigation_tools.py` — the execute POST passes
  `NAVIGATION_EXECUTE_TIMEOUT_S = 180`, the route's own worst case (5 + 30 + 5 + 120 = 160 s) plus
  slack.

Why a longer timeout and not polling: the route only returns an `execution_id` (which the tool
already polls) when the host runs the navigation asynchronously; for web devices it blocks until
the end, so there is nothing to poll during the call. Making the route asynchronous would change
the frontend and scripts that call it too; matching the client timeout to the server's is the
smallest change. A client reaching the server through a proxy with a shorter limit (Cloudflare,
100 s) can still be cut off on a navigation longer than that; the observed 20–93 s fit.

## Verification

- `python3 -m pytest -m unit tests/backend_server/test_mcp_navigate_timeout.py` — the execute
  POST is sent with the 180 s timeout.
- After deploy: on a freshly restarted host (cold cache), the first `navigate_to_node` reaches the
  target in one call.

### Live check (2026-10-05, node1)

MCP `take_control` + `navigate_to_node` on host-clone-1/host (youtube-web) right after a server restart (`cache_ready: false`): search_results returned in 14.3 s, home in 10.3 s, both direct one-step edges, no client timeout. The 180 s client timeout alone was not enough: on 10032 the call still hung (MCP poll capped at 60 s, run restarted from the entry edge) until BUG-0411 shipped in the same server deploy.
