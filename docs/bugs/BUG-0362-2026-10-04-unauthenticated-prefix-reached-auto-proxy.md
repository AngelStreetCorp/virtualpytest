# BUG-0362 — An unauthenticated path prefix let anonymous requests reach the host proxy

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                          |
|-----------|--------------------------------------------------------------------------------|
| ID        | BUG-0362                                                                       |
| Reported  | 2026-10-04 (security review of TASK-49 report sharing)                         |
| Status    | Fixed, deployed and verified 2026-10-04                                        |
| Severity  | Critical: anonymous requests reached the route that calls hosts with the server's API key |
| Area      | `backend_server/src/app.py` (global auth guard), `backend_server/src/routes/auto_proxy.py` |
| Fixed in  | Unreleased                                                                     |

---

## Symptom

On the public domain, with no credential at all:

```
curl --path-as-is https://<domain>/server/share/%2e%2e/report-snapshots/config
→ 400 {"error":"host_name required in request body or query parameters"}
```

The same for `/server/share/a/b/c` and `/server/health/%2e%2e/...`. A 400 from the `auto_proxy`
handler means the request had passed the auth guard: it should have been a 401.

## Root cause

The global guard lets a request through without a principal when its **path** starts with an
entry of `UNAUTHENTICATED_SERVER_PREFIXES` (`/server/health`, `/server/share`, `/server/mcp`, …).
It never checked which **route** the path resolved to. Any path under such a prefix that no
dedicated route matches falls through to `auto_proxy` (`/server/<path:endpoint>`), the
catch-all that forwards `/server/X` to `/host/X` on the host named in the body, using the
server's API key. With dot segments (`/server/health/../actions/executeBatch`) the HTTP client
normalises the forwarded URL to a real host endpoint, so device actions were reachable
anonymously.

It predates TASK-49: every exempt prefix had it. Adding `/server/share` (TASK-49) added one
more prefix with the same gap, and the TASK-49 security review found it.

## Fix

- The guard exempts a prefix only when the request resolves to a dedicated route
  (`request.endpoint` set and not `auto_proxy.*`). Everything that reaches the catch-all is
  authenticated like any other path.
- `auto_proxy` refuses an endpoint with a `.` or `..` segment (400), even for an authenticated
  caller, so `/server/x/../y` can never be forwarded as another host path.
- Tests: `tests/backend_server/test_exempt_prefix_catch_all.py` (4 of its 5 tests fail without
  the fix).

## Edge mitigation (while the deploy waited on run leases)

The proxy's `sites-enabled/virtualpytest` got one rule in the `virtualpytest`, `virtualpytest-demo`
and `rpitest` server blocks: `$request_uri` on `/server/` with a dot segment (`/..`, `/.`, raw or
`%2e`/`%2f`-encoded) returns 400. It applied at once with a reload, no restart. It does **not**
cover `rpitest.angelstreet.io`, whose Cloudflare record reaches the Pi server directly, not this
proxy; that domain stayed open until the server deploy (about 30 minutes).

## Verification (2026-10-04, after the deploy, on the server and on vpt-pi1)

| Request (anonymous) | virtualpytest.angelstreet.io | rpitest.angelstreet.io |
|---|---|---|
| `/server/health/%2e%2e/report-snapshots/config` | 400 (edge rule) | 401 |
| `/server/share/a/b/c` | 401 | 401 |
| `/server/health/x/y` | 401 | 401 |
| `/server/health` | 200 | 200 |

Before the fix every request in the first three rows answered 400 "host_name required" from the
host proxy. Share links still open logged out (browser run on the deployed build).
