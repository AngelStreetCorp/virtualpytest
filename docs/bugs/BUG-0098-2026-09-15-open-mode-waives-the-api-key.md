# BUG-0098 — `SERVER_OPEN_MODE=true` waived the server API key too, and a wrong `X-API-Key` fell through instead of failing

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                   |
|-----------|--------------------------------------------------------------------------|
| ID        | BUG-0098                                                                 |
| Reported  | 2026-09-15                                                               |
| Status    | **Fixed in code (pending deploy).**                                       |
| Severity  | High (unauthenticated admin access to `/server/*` on open-mode installs)   |
| Area      | `backend_server/src/lib/auth_middleware.py` · `/server/*` global guard     |
| Fixed in  | build 9151                                                                 |

---

## Symptom

On a deployment installed with the default posture, every `/server/*` route answered
a plain `curl` — no credential of any kind — and did so **as `admin`**, so
`@require_role('admin')` gates passed as well.

```
curl https://<install>/server/system/info      # 200, no header sent
```

Our own `virtualpytest.angelstreet.io` was not affected (it runs with a JWT secret and
open mode off, and correctly answers 401), which is why this survived unnoticed.

## Root cause — one axis swallowing the other

`/server/*` has two *independent* credentials:

| Axis | Credential | Who carries it |
|---|---|---|
| server API | `API_KEY` via `X-API-Key` | hosts, CI, provisioning, scripts — machine callers |
| user login | Supabase JWT | browser users |

`SERVER_OPEN_MODE` is meant to waive the **login** axis, for a lab or an appliance with
no Supabase accounts. Instead it returned early from the guard before either axis was
considered:

```python
if is_server_open_mode():
    _log_open_mode_warning_once()
    request.user_role = _get_server_public_role()   # default 'admin'
    return None                                     # ← nothing else is ever checked
```

So a configured `API_KEY` — which the installer always generates — bought nothing. The
key is the credential of the *server API*; it has no relationship to frontend login and
should never have been waived by a switch about login.

### A second, quieter bug on the same path

`_is_valid_service_api_key()` returns `False` for both "no key sent" and "wrong key
sent", and the guard simply continued to the next branch. A service with a typo'd key
therefore got whatever the *next* branch decided: `200` as admin on an open-mode
install, `401` on a JWT one. The same caller appeared to work on one deployment and
failed on another with no way to tell why. The intended behaviour was already written
down in `docs/agent/platform/SERVER_AUTH.md` §3 ("a present but invalid strong
`X-API-Key` short-circuits to 401 — no fall-through, clear errors for services") and had
never been implemented.

## Why the default is open in the first place

Nothing in the customer overlay can influence this — `deploy_customer.sh` refuses an
overlay that carries any `.env` and excludes `.env` from both rsyncs, so the posture is
whatever the *first install* wrote and no later deploy revisits it. The installer
defaults `OPEN_MODE="true"` (`setup/local/linux/shared/write_env.sh:21`) and writes it
with `FORCE=1` (`:122`), which also overwrites an operator who had set it to `false`.
That part is tracked separately; this bug is about the guard treating a configured
`API_KEY` as irrelevant.

## Fix

Both axes are now evaluated in order, and neither waives the other.

1. **A present `X-API-Key` is validated strictly.** Valid → allowed as the `service`
   principal; invalid → `401`, never a fall-through. This runs first, so it is
   unaffected by open mode and by the JWT posture.

2. **Open mode waives the browser login only.** When `API_KEY` is configured, a
   non-browser request must still present it:

   ```python
   if is_server_open_mode():
       if is_api_key_configured() and not _looks_like_browser():
           return jsonify({'error': 'unauthorized', ...}), 401
   ```

   `_looks_like_browser()` reads `Sec-Fetch-Site` / `Sec-Fetch-Mode` / `Origin`.
   Browsers set `Sec-Fetch-*` on every fetch, XHR and navigation and page scripts can
   neither forge nor omit them (forbidden header names); `curl`, `requests` and
   scanners send none of them. A no-login deployment's own SPA — which has no
   credential to send — therefore keeps working, while `curl /server/...` is refused.

**This is a speed bump, not a boundary.** `curl -H 'Sec-Fetch-Site: same-origin'`
passes. It has the same security value as the `SERVER_PUBLIC_KEY` scheme it replaces in
practice, with no key to generate, no `VITE_` var and no frontend rebuild. A deployment
that needs a real boundary configures `SUPABASE_JWT_SECRET` and leaves open mode off —
then every browser call carries a JWT and the heuristic is never consulted.

## Callers fixed alongside

Three non-browser callers reached `/server/*` with no service key. All three were
already broken on any login-enforcing deployment; change 2 would also have broken them
on an open-mode one.

| Caller | Route | Fix |
|---|---|---|
| `backend_host/src/builder/blocks/api_call.py` | `/server/postman/test` | now sends `server_auth_headers()` |
| `scripts/atlas_chat.py` | `/server/agent/sessions`, `/server/control/takeover` | sends `X-API-Key` when `API_KEY` is exported |
| `scripts/feature_delivery_report.py` | `/server/cicd/runs` | same |

Host→server registration, the MCP surface, the Slack webhook, `cicd/ingest` and the
`taskComplete` callbacks were checked and need no change — they either already send the
key (`shared/src/lib/utils/build_url_utils.py::server_auth_headers`) or sit on the
guard's allowlist in `app.py`.

## Verification

`tests/backend_server/test_auth_guard.py` — 13 unit tests in a Flask request context,
no live server needed. The matrix they lock in:

| Posture | Caller | Before | After |
|---|---|---|---|
| open mode | browser, no credential | 200 | 200 |
| open mode | browser navigation | 200 | 200 |
| open mode | `curl`, no credential | **200 as admin** | **401** |
| open mode | `curl`, valid key | 200 | 200 |
| open mode | `curl`, **wrong** key | **200 as admin** | **401** |
| open mode, no `API_KEY` set | `curl` | 200 | 200 (nothing to enforce) |
| closed | browser, no credential | 401 | 401 |
| JWT enforced | browser, no token | 401 | 401 |
| JWT enforced | `curl`, **wrong** key | 401 | 401 |

## Operator action

On any install running open mode, no `.env` change is required to get the fix — the key
is enforced as soon as the new code is deployed. To go further and require a login,
set `SERVER_OPEN_MODE=false` with a real `SUPABASE_JWT_SECRET` and confirm the startup
banner reads `JWT ENFORCED`:

```bash
journalctl -u vpt-server | grep '/server/\* auth'
```
