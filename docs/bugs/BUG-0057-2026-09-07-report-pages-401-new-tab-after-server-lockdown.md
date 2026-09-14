# BUG-0057 — Report pages opened in a new tab get 401 after the /server/* lockdown

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0057                                                     |
| Reported  | 2026-09-07                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium (CI/CD, DOM and API-testing report pages unusable while logged in) |
| Area      | backend_server auth guard · frontend fetch interceptor       |
| Fixed in  | build 8713                                                   |
| Commit    | `0224543ad`                                                        |

---

## Symptom

Logged in as admin, opening a CI/CD report from Test → Report
(`/server/cicd/report/<run>/<job>/?team_id=…`) shows:

```
{"error":"Authentication required","message":"Authorization header is required"}
```

Same for the Interface page's "Open DOM" tab and the API-testing HTML report.

## Root cause

`/server/*` is closed by default since 2026-09-07 (BUG-0055 context). The SPA authenticates by
attaching the Supabase JWT as an `Authorization` header from its fetch interceptor. A page opened
with `window.open` / an `<a href>` is a plain browser navigation: the interceptor never sees it
and a tab cannot set request headers, so the guard saw no credential.

## Fix (`0224543ad`)

The credential is mirrored into a cookie the browser sends on navigations:

- **Frontend** (`installFetchAuth.ts`): on install and on every Supabase auth state change,
  write `vpt_jwt=<access_token>` with `Path=/server/`, `SameSite=Strict`, `Secure` on https and
  `Max-Age` = token lifetime; cleared on sign-out. No-JWT deployments get `vpt_server_key`
  (the published `VITE_SERVER_PUBLIC_KEY`) the same way.
- **Server** (`auth_middleware.py`): `require_user_auth` and the `X-Server-Key` check fall back
  to those cookies **only when no header is present and only for GET/HEAD**. The JWT is verified
  exactly as a header token. A cookie can therefore never authorise a state-changing request,
  and `SameSite=Strict` keeps it off cross-site requests entirely.

Limitation: cookies are per origin, so a report served by a *different* server origin than the
frontend (e.g. the rpitest server opened from the main UI) still needs its own session there.

## Verification

Flask test client with a signed HS256 token: no credential → 401; `Authorization` header → 200;
cookie on GET → 200; cookie on POST → 401; tampered cookie → 401.

## Follow-ups

- Deploy server (`0224543ad`) and rebuild the frontend; existing sessions get the cookie on the next
  auth-state event or page load.
