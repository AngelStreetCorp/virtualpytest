# BUG-0070 — `SERVER_OPEN_MODE=true` was silently ignored when a `SUPABASE_JWT_SECRET` was present

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0070                                                                    |
| Reported  | 2026-09-09 (customer site, first packaged delivery)                         |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | High on a no-login site (every browser call to `/server/*` answered 401 after the deploy) |
| Area      | backend_server/src/lib/auth_middleware.py · backend_server/src/app.py       |
| Fixed in  | Unreleased                                                                  |
| Commit    | this commit                                                                 |

---

## Symptom

Right after deploying build 8713 with the runbook's one auth line appended to the server
`.env` (`SERVER_OPEN_MODE=true`, TASK-13 §3-A posture 3), the UI showed
`Error: Authentication required` and every `/server/*` request (`getAllHosts`, `lockedDevices`,
`workspaces`, `branding`…) returned 401. Hosts kept registering and pinging (they authenticate
with `X-API-Key`). Server and frontend services were healthy.

## Root cause

The global guard checked the credentials in this order: X-API-Key → auto-sign → **JWT if a
`SUPABASE_JWT_SECRET` is configured** → X-Server-Key → open mode → 401. The site has no
browser login (no `VITE_SUPABASE_URL` in the frontend), but its server `.env` still carried a
real `SUPABASE_JWT_SECRET` from the Supabase database install. That secret made the guard take
the JWT branch — which returns 401 straight away when no token is presented — so the explicit
`SERVER_OPEN_MODE=true` further down was never reached. The startup banner said `JWT ENFORCED`
and gave the operator no hint that the open-mode line was being ignored.

The runbook did document the caveat ("only valid when there is no JWT secret") and had a
pre-check for it (§5.2 step 7), but a documented trap is still a trap: the operator stated an
intent in one line and a leftover value from another subsystem overrode it.

## Fix

- `auth_middleware.enforce_user_auth_if_enabled_for_request()`: open mode is evaluated right
  after the service key and auto-sign checks, **before** the JWT branch. New order:
  X-API-Key → auto-sign → **open mode** → JWT (if secret) → X-Server-Key (if no secret) → 401.
  Open mode still names the principal introduced by BUG-0064 (`SERVER_PUBLIC_ROLE`, default
  admin). The legacy `ENFORCE_FRONTEND_JWT=true` + missing-secret 503 is also skipped under
  open mode.
- `app.py` startup banner: `OPEN MODE` is printed whenever the flag is set; when a secret is
  also configured the banner adds that it is ignored for `/server/*` and how to re-enable JWT
  (remove `SERVER_OPEN_MODE`).
- Docs: `SERVER_AUTH.md` §1 order list, `.env.example`, TASK-13 §3-A.

Security posture unchanged: open mode remains an explicit opt-in (default off); a deployment
without the line behaves exactly as before (secret ⇒ JWT, else X-Server-Key, else 401).

## Verification

Flask test request context, `SERVER_OPEN_MODE=true` **with** a configured secret:
guard → allow, `request.user_role == admin`, gated route passes. Same secret **without** the
flag: 401 (JWT enforced, as before). No secret, no flag: 401 (closed). `py_compile` clean.

## Workaround on build 8713 (applied on site 2026-09-09)

```bash
sudo cp /opt/virtualpytest/.env /opt/virtualpytest/.env.bak-$(date +%F-%H%M)
sudo sed -i 's/^SUPABASE_JWT_SECRET=/#no browser login on this site, open mode instead: SUPABASE_JWT_SECRET=/' /opt/virtualpytest/.env
sudo systemctl restart vpt-server      # banner must say OPEN MODE
```
