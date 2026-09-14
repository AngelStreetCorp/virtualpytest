# BUG-0045 — Agent Dashboard shows "Failed to load agents from API: Failed to fetch" (slash redirect built as http:// behind the proxy)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0045                                                     |
| Reported  | 2026-09-03                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium (Agent Dashboard unusable on the public https site)   |
| Area      | `backend_server/src/routes/agent_registry_routes.py`, `server_device_flags_routes.py` |
| Fixed in  | build 8713                                                   |
| Commit    | `25e138f1e`                                                  |

---

## Symptom

On `https://virtualpytest.angelstreet.io/agent-dashboard` the page shows a red banner
*"Failed to load agents from API: Failed to fetch. Check backend server status."* although the
server is up. The CI page-screenshot suite (`e2e-pages`) failed on that page in every run
(runs #142 and #147 after the timeout fix made the assertion reachable).

## Root cause

The agents blueprint is mounted at `/server/agents` and its list route is declared as `'/'`.
The frontend calls `/server/agents?team_id=…` (no trailing slash). With Flask's default
`strict_slashes=True` the server answers **308 → `/server/agents/`**, and because the app runs
behind the reverse proxy it builds that `Location` with the scheme it sees: **`http://`**.

```
GET https://virtualpytest.angelstreet.io/server/agents?team_id=…
HTTP/2 308
location: http://virtualpytest.angelstreet.io/server/agents/?team_id=…
```

A browser on an https page refuses to follow an http redirect (mixed content), so `fetch`
rejects with the generic *Failed to fetch*. `curl -L` follows it and gets 200, which is why the
API looked healthy from the command line. `/server/device-flags` has the identical shape
(unused by the frontend at the root path, but the same trap).

## Fix

`strict_slashes=False` on both root routes: the slash-less URL is served directly, no redirect.
(`mcp_routes.py` already did this for `/server/mcp`.)

## Verification

- Before: public probe shows the 308 with an `http://` Location (above); e2e-pages run #147
  fails with `Backend "Failed to fetch" banner visible on Agent Dashboard` after 15.8 s.
- After deploy: `curl -sI "https://virtualpytest.angelstreet.io/server/agents?team_id=…"` must
  return 200 directly, and the e2e-pages job must pass 38/38.
