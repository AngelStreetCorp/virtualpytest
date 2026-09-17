# BUG-0092 — CORS reflected any origin with credentials enabled

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0092                                                     |
| Reported  | 2026-09-15                                                   |
| Status    | Fixed, deployed to the lab server, verified live              |
| Severity  | High                                                          |
| Area      | backend_server / backend_host — shared Flask app setup        |
| Fixed in  | build 9151                                                    |
| Commit    | TBD                                                           |

---

## Symptom

Neither `/server/*` nor `/host/*` have any IP or origin restriction at the nginx layer — verified
against every shipped nginx template, including `production-https.conf`. The only origin-based
control in front of either API was CORS, configured as:

```python
CORS(app, origins="*", supports_credentials=True, max_age=86400)
```

Flask-CORS' documented behaviour for `origins="*"` combined with `supports_credentials=True` is
to **reflect whatever `Origin` header the caller sends**, rather than emit a literal `*` (the
CORS spec forbids a literal wildcard alongside credentials). Verified live against a production
deployment before the fix:

```
$ curl -s -D - -o /dev/null https://api.virtualpytest.com/server/devices \
    -H "Origin: https://evil.example.com" -H "Access-Control-Request-Method: GET" -X OPTIONS
HTTP/2 200
access-control-allow-origin: https://evil.example.com
access-control-allow-credentials: true
access-control-allow-methods: DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT
```

Any web page, on any site, could make a fully credentialed cross-origin request to the API and
read the response.

## Root cause

`shared/src/lib/utils/app_utils.py`'s `setup_flask_app()` — shared by both `backend_server` and
`backend_host` — hard-coded the wildcard with a comment claiming *"nginx handles access
control"*. It does not: none of the shipped nginx templates gate `/server/` or `/host/` by IP or
origin. Two of the project's own docs (`docs/get-started/security.md` and `cloud-setup.md` §4.1)
independently claimed `CORS(app, ...)` was *never called at all* — also wrong, and itself a sign
this code path had drifted out of anyone's mental model of the system.

## Why this did not mean session hijacking

Authentication here is a bearer token / `X-Server-Key` header the frontend's own JavaScript
attaches to each request — not a cookie. A malicious page cannot make a victim's browser
auto-attach either one (that is what a cookie does; a header does not get attached by the
browser on the attacker's behalf), and cannot read either value out of the frontend's
`localStorage` cross-origin (browser storage isolation, unrelated to CORS). So this specific
configuration did not enable classic cookie-based CSRF / session-riding.

What it did enable: `SERVER_PUBLIC_KEY` (the no-login admin key shipped in every frontend bundle
as `VITE_SERVER_PUBLIC_KEY`, already documented as "weak by design" in `auth_middleware.py`) is
public — anyone who has ever loaded the frontend, or read the public repo, can read it. Before
this fix, a malicious **page**, not just a malicious **script run directly against the API**,
could use that key on behalf of any visitor who merely loaded the page, and — because CORS
allowed it — read the JSON response too. It also meant that if cookie-based auth is ever added
to either app in the future, this configuration would make it immediately exploitable with no
further warning.

## Fix

- `shared/src/lib/utils/app_utils.py`: origins now come from `CORS_ALLOWED_ORIGINS` (env,
  comma-separated — same convention as `PUBLIC_ASK_ALLOWED_ORIGINS` in
  `server_public_ask_routes.py`). Unset, it falls back to the vendor's own known frontend
  domains (see `.env.example`), not a wildcard. Applied to both the HTTP `CORS(...)` call and
  the `SocketIO(..., cors_allowed_origins=...)` call (both branches: Linux/gevent and
  Windows/threading), which carried the same `"*"`.
- `.env.example`, `docs/get-started/configuration.md`: `CORS_ALLOWED_ORIGINS` documented.
- `docs/get-started/security.md`, `docs/get-started/cloud-setup.md` §4.1: corrected — both
  previously claimed CORS was never wired up at all.
- `docs/get-started/production-checklist.md` §2b: new section — what changed, why it mattered,
  and the exact steps + verification curl command to confirm a given deployment has the fix.

## Verification

- Local: `_cors_allowed_origins()` returns the vendor-domain default when `CORS_ALLOWED_ORIGINS`
  is unset, and exactly the configured list (trimmed, trailing slashes stripped) when it is set.
- `python3 -m py_compile shared/src/lib/utils/app_utils.py` — clean.
- CI (run for `f092aae7ee`): 549 backend tests passed, all E2E suites (smoke/viewport/all-pages)
  green, API route sweep 154/154 passed — the shared `setup_flask_app()` change did not break
  anything that touches it.
- **Deployed to the lab server (`vpt-server.service` on `.103`, `api.virtualpytest.com`) and
  verified live 2026-09-15**, `CORS_ALLOWED_ORIGINS` left unset (exercising the code default):
  - `Origin: https://evil.example.com` → **no** `access-control-allow-origin` header at all,
    on both a plain request and an OPTIONS preflight (before the fix: reflected verbatim with
    `access-control-allow-credentials: true`).
  - `Origin: https://virtualpytest.angelstreet.io` (the real, currently-deployed frontend) →
    still gets `access-control-allow-origin: https://virtualpytest.angelstreet.io` +
    `access-control-allow-credentials: true` — the default allowlist did not break the one
    cross-origin caller this deployment actually has.
  - `/server/devices` without a token → still `401` — auth is unaffected, as expected (CORS and
    authentication are independent checks).
- **Still open**: every OTHER deployment (customer instances, self-hosted installs, the second
  environment on proxmox3/QualiAI, backend_host directly if it is ever reachable on its own
  origin) still needs its own redeploy + the same verification — this fix landing on one server
  does not touch the others. Tracked in `docs/get-started/production-checklist.md` §2b.

### Unrelated, noticed during the deploy

The deploy host's `~/virtualpytest` checkout was on an unrelated feature branch
(`feat/mobile-app`, another session's active work, 9 commits ahead of `main`) — deployed from a
separate throwaway clone instead so that checkout was not touched. `update_core.sh --server`'s
target list (`SERVER_IP="192.168.0.103,host1"`) also tried a second target named `host1`, which
failed to resolve from this shell (`ssh: Could not resolve hostname host1`) — pre-existing,
unrelated to this fix, not investigated further here.
