# BUG-0097 — A password reset sent as a `GET` answers `200` and looks like it worked

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0097                                                     |
| Reported  | 2026-09-15                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend — user provisioning (`/server/users`)                |
| Fixed in  | build 9151                                                   |
| Commit    | TBD                                                          |

---

## Symptom

The one call an integrator makes to reset someone's password on VirtualPyTest and Grafana at once
is a `PUT` ([user provisioning](../integrations/user-provisioning.md)):

```bash
curl -X PUT "https://<server>/server/users/someone@example.com?grafana=true" \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"password": "the new password"}'
```

Drop the `-X PUT` (and the `-d`, or curl sends `POST`) and curl sends a `GET` to the same address.
The password is never changed — but the response is a success:

```
GET /server/users/someone@example.com?grafana=true
200 {"status":"ok","exists":true,"email":"someone@example.com",
     "platform":{"user_id":"…","role":"viewer","team":"Default Team"}}
```

Reproduced against the deployed server on 2026-09-15. `"status":"ok"` plus `"exists":true` is
indistinguishable from a successful reset to a caller that only checks the status code, so the
person is handed a password that was never set and the failure surfaces at their next login.

## Root cause

`GET /server/users/<user_id>` serves two different things. With a UUID it returns the full profile
for the VirtualPyTest UI; with an email it is the read-only provisioning status check (§3.4 of the
provisioning design) — it answers `200 {"exists": …}` and deliberately never 404s, so an external
system can ask "does this person exist?" without handling an error.

That read-only branch answered any `GET`, including one that plainly carried write intent. Nothing
looked at `?grafana=true` (a mirror flag that has no meaning on a read) or at a `password` in the
body: both were ignored, and the read's own `200` was returned.

## Fix

`backend_server/src/routes/server_users_routes.py` — in `get_user()`, before the status read, a
`GET` on an email address that carries write intent (`?grafana=`, or a `password` in the body or
query) is answered `405` with `Allow: GET, PUT, DELETE` and the call the caller meant:

```json
{
  "status": "error",
  "error": "method_not_allowed",
  "detail": "GET only reads this user's status and never changes a password. To set the password, use: PUT /server/users/someone@example.com?grafana=true with body {\"password\": \"...\"}."
}
```

A plain `GET` with no write intent is unchanged — still the `200 {"exists": …}` status check the
provisioning contract promises.

`docs/integrations/user-provisioning.md` gained a "Keep the `-X PUT`" note under *Reset a password*
and a `405` row in the errors table.

## Verification

`tests/backend_server/test_users_provisioning.py` (4 tests):

- `PUT …?grafana=true` with a password → `200`, `action` set, `grafana` key present (the mirror ran)
- `GET …?grafana=true` → `405`, `Allow` contains `PUT`, `detail` names the `PUT`
- `GET` with a `password` body → `405`
- plain `GET` on an absent email → `200 {"exists": false}` (status check unregressed)

The lifecycle test writes only `provisioning.ci@vpt.local` and deletes it in a `finally`.

Run against a deployed server:

```bash
export API_KEY=…; export SERVER_URL="https://<server>" VERIFY_SSL=false
python3.12 -m pytest tests/backend_server/test_users_provisioning.py -q
```

Before the fix, run against the deployed server: 2 passed, 2 failed (both `GET` guards returned
`200`). The `PUT → 200` test passed both before and after — that half was never broken.
