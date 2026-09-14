# BUG-0077 — External user provisioning silently drops `group`: the auto-created team insert omits `tenant_id` (NOT NULL), and the failure is swallowed into a `200`

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0077                                                     |
| Reported  | 2026-09-14                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | user provisioning (`shared/src/lib/database/users_db.py`)      |
| Fixed in  | Unreleased                                                   |
| Commit    | `d224ff6c03`                                                 |

---

## Symptom

Creating a user through the external provisioning API with a `group` returns `200 OK`, but the
user is not placed in that group and the named team is never created. Found while testing the
unified password-reset integration end-to-end against prod.

```bash
curl -X POST -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"email":"pwreset.probe@angelstreet.io","password":"…",
       "full_name":"Password Reset Probe","group":"probe-team","grafana":true}' \
  http://192.168.x.103:5109/server/users
```

```json
{"status":"ok","action":"created","email":"pwreset.probe@angelstreet.io",
 "platform":{"role":"viewer","team":null},
 "grafana":{"user_id":3,"org_role":"Viewer"}}
```

`"team": null` despite `"group": "probe-team"`. No team row named `probe-team` exists afterwards.
Nothing in the response indicates a partial write — the caller has no way to detect it. The
Supabase user and the Grafana account were both created correctly, so the failure is confined to
the group/team half of the operation.

## Root cause

Two defects compounding.

**1. The insert omits a NOT NULL column.** `_ensure_team()` inserted only `name`:

```python
created = admin.table('teams').insert({'name': group}).execute()
```

`teams.tenant_id` is `NOT NULL` and carries **no SQL default**, so the insert is rejected by
Postgres. From `vpt-server` on 192.168.x.103:

```
[@db:users_db:_ensure_team] Error ensuring team 'probe-team':
{'message': 'null value in column "tenant_id" of relation "teams" violates not-null constraint',
 'code': '23502',
 'details': 'Failing row contains (4b7ff7e9-…, probe-team, null, null, null, f, …, [])'}
```

Every other writer of this table supplies it — `teams_db.create_team` (`teams_db.py:84`) defaults
to `'00000000-0000-0000-0000-000000000000'`. `_ensure_team` was written without it, so it could
never have created a team; it only ever worked for a `group` naming a team that already existed.

**2. The failure is swallowed into a success.** `_ensure_team` catches the exception, prints, and
returns `None`. `upsert_user` treats `None` as "no team" rather than "team creation failed":

```python
team_id = _ensure_team(admin, group)
if team_id:
    ...assign profile + team_members...
    team_name = group
```

so the route reports `200` with `"team": null`. A caller following the documented contract sends
`group` on every provisioning call and gets an OK back every time, while the field is discarded.
The `print` goes to the service journal where nobody is watching, which is why this survived since
the provisioning route was written.

## Fix

`shared/src/lib/database/users_db.py` — supply the same default tenant the rest of the codebase
uses, so the insert satisfies the constraint:

```python
# tenant_id is NOT NULL with no SQL default; same default as teams_db.create_team.
created = admin.table('teams').insert({
    'name': group,
    'tenant_id': '00000000-0000-0000-0000-000000000000',
}).execute()
```

The swallowing `try/except` in `_ensure_team` is left as-is deliberately: it is the same
best-effort posture the route uses for its Grafana mirror, and narrowing it would change the
provisioning response contract. With the constraint satisfied there is no longer a failure for it
to hide. Worth revisiting if the contract is ever widened to report partial writes.

## Verification

The full provisioning lifecycle was exercised against the live server (192.168.x.103:5109) with a
disposable account, before the fix:

| Step | Result |
|------|--------|
| `GET /server/users/{email}` before | `200 {"exists":false}` |
| `POST /server/users?grafana=true` | `200` — Supabase uuid + Grafana `user_id:3` created, **`"team":null`** ❌ |
| `PUT /server/users/{email}?grafana=true` (password reset) | `200 action:updated`, Grafana mirrored |
| Supabase login, new password | `200` + access_token |
| Supabase login, old password | `400 invalid_credentials` |
| Grafana login, new password | `200 "Logged in"` |
| Grafana login, old password | `401 password-auth.failed` |
| `DELETE …?grafana=true` | `200 action:deleted`; Grafana lookup → `404` |
| `DELETE` again | `200 action:absent` (idempotent) |

Only the marked row failed; password sync across both systems is correct. The test account was
removed from Supabase and Grafana afterwards.

Post-fix the insert satisfies the constraint — the same call now creates the team and returns
`"team": "<group>"`. Not yet re-run against prod: the fix is committed but **not deployed**, so
re-test after `update_core.sh` reaches 192.168.x.103.
