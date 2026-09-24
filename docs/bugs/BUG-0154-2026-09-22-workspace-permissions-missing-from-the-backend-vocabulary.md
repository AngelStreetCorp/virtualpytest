# BUG-0154 — The permission matrix API answers differently from the permission checks it describes

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0154                                                     |
| Reported  | 2026-09-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | backend / docs                                               |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

`GET /server/permissions/matrix` and `GET /server/users/:id/permissions` reported an admin as
holding 63 permissions while the Users page rendered 68 checkboxes. The five missing strings were
`org.workspaces:view`, `:create`, `:edit`, `:delete` and `:manage_members` — offered in the admin
UI, absent from every API answer about what an admin may do.

A second, independent miscount in the same function: `_compute_effective()` subtracted
`denied_permissions` from **every** role, admins included. Enforcement does not — both
`require_permission()` and the frontend `PermissionContext` return early on `role == 'admin'`
before denials are read. So an admin carrying a leftover denial from an earlier role (deny
`testcases:delete` on a tester, then promote them) was reported as lacking a permission they in
fact hold, and the API was the only thing in the system saying so.

No user was wrongly allowed or refused by either half: the workspace routes never consulted these
strings (see below), and admins bypass permission checks anyway. The damage was to anything reading
the matrix API to reason about access — a provisioning caller, a support answer, an audit.

## Root cause

The permission vocabulary is duplicated, with nothing pinning the copies together:

- `ALL_PERMISSIONS` in `frontend/src/types/auth.ts` — drives the checkbox list and the admin
  expansion `ADMIN_ALL_PERMISSIONS`
- `_ALL_PERMISSIONS` in `backend_server/src/routes/server_permissions_routes.py` — what
  `_compute_effective()` hands back as `role_permissions` for an admin

`org.workspaces:*` was added to the frontend list only. The checklist in
`docs/agent/platform/USER_PERMISSION.md` §10 named just the frontend file, so following it
reproduced the drift.

The denial miscount is the older mistake of the two: `_compute_effective()` was written to the
*model* in the docs (`role u team u individual - denied`) rather than to what `require_permission()`
actually does, where the admin branch returns before denials are consulted. The model's own footnote
says denials never apply to admins; the function did not implement its own footnote.

Separately, those five permissions were **declared but not enforced**: every route in
`backend_server/src/routes/server_workspaces_routes.py` was `@require_admin_role`, so the
checkboxes round-tripped to `profiles.permissions` and changed nothing. That is what made the
count mismatch invisible for so long — nothing consulted the strings, so nothing could disagree
about them.

## Fix

- `backend_server/src/routes/server_permissions_routes.py` — added the five `org.workspaces:*`
  strings to `_ALL_PERMISSIONS`, with a comment recording that they are reported, not enforced.
  Both vocabularies are now 68 entries and identical.
- `backend_server/src/routes/server_permissions_routes.py` — `_compute_effective()` no longer
  subtracts denials for an admin, matching `require_permission()`. `denied_permissions` is still
  returned in the breakdown, so a leftover denial stays visible to whoever is reading; it simply no
  longer pretends to have taken effect.
- `docs/agent/platform/USER_PERMISSION.md` — §10 step 1 now names both files; new "Declared ≠
  enforced" note under §3; §8 documents that the Users page Permissions tab shows overrides only.
- `backend_server/src/routes/server_workspaces_routes.py` — the nine gated routes moved from
  `@require_admin_role` to `@require_permission('org.workspaces:<action>')`: `:view` for the three
  reads, `:create` / `:edit` / `:delete` for the workspace itself, `:manage_members` for the three
  member mutations. **Default access is unchanged** — `org.workspaces:*` is in no role's defaults,
  so an ungranted tester or viewer still gets 403, and admins and the service key still pass. What
  changes is that an admin can now delegate workspace administration with a grant, which is what
  the checkboxes always implied.
- `backend_server/src/routes/server_workspaces_routes.py` — `GET /workspaces/user/<user_id>` took
  a user id from the path and carried no check at all, so any authenticated caller could read
  anyone else's workspace list by editing the URL. It cannot carry a gate: every signed-in
  principal calls it for itself on each page load to fill the workspace switcher, so gating it on
  workspace administration would empty the switcher for testers and viewers. It now allows reading
  for yourself, and requires `org.workspaces:view` to read for somebody else.
- `backend_server/src/lib/auth_middleware.py` — the resolution was inline in
  `require_permission()`, which is why the route above would have needed a fourth copy of it.
  Extracted as `principal_holds_permission(permission) -> bool`, with the role table beside it as
  `ROLE_DEFAULT_PERMISSIONS`; the decorator is now a wrapper that turns `False` into a 403.
- `tests/backend_server/test_permission_resolution.py` — new, offline (Flask request context, no
  live server): 20 tests over the resolution order, and a parity test pinning the two vocabularies
  against each other, which is what would have caught this.
- `docs/agent/platform/ORG_MANAGEMENT.md` — "all three entities are admin-only" is no longer true
  of workspaces; the endpoint table names the permission each route requires.
- `docs/user-guide/permissions.md` — documents team-level grants (previously unmentioned, though
  enforced since 2026-09-17), explains that an empty Permissions tab is the normal state, and drops
  a stale example: it offered "a viewer who may also run one specific kind of test" as the reason
  to grant, which the viewer read-only floor (`enforce_viewer_read_only()`, shipped with BUG-0130)
  has made impossible — a viewer is refused every non-GET before their grants are consulted.

The three role-default copies (`auth_middleware.py` `role_defaults`, `_ROLE_PERMISSIONS`,
`ROLE_PERMISSIONS` in `auth.ts`) were checked at the same time and already agreed — tester 32,
viewer 11.

## Verification

Both vocabularies parse to the same 68 strings:

```bash
python3 - <<'PY'
import re
def perms(t): return set(re.findall(r"'([a-z_]+(?:\.[a-z_]+)?:[a-z_]+)'", t))
ts=open('frontend/src/types/auth.ts').read()
py=open('backend_server/src/routes/server_permissions_routes.py').read()
a=perms(ts[ts.index('ALL_PERMISSIONS'):ts.index('\n]', ts.index('ALL_PERMISSIONS'))])
b=perms(py[py.index('_ALL_PERMISSIONS = ['):py.index('\n]', py.index('_ALL_PERMISSIONS = ['))])
print(len(a), len(b), a ^ b)
PY
```

Expected: `68 68 set()`.

Then `GET /server/users/<admin_id>/permissions` returns 68 entries under both `role_permissions`
and `effective` — including for an admin whose `denied_permissions` is non-empty, which before this
fix returned `68 - len(denied)` under `effective`.

`_compute_effective()` is pure and takes a plain dict, so both halves can be exercised without a
server:

```bash
python3 - <<'PY'
src = open('backend_server/src/routes/server_permissions_routes.py').read()
ns = {}
exec(src[src.index('_ROLE_PERMISSIONS'):src.index('@server_permissions_bp.route')], ns)
ce = ns['_compute_effective']
a = ce({'role': 'admin', 'permissions': [], 'team_permissions': [],
        'denied_permissions': ['testcases:delete']})
print(len(a['role_permissions']), len(a['effective']))   # 68 68
t = ce({'role': 'tester', 'permissions': ['org.workspaces:view'],
        'team_permissions': ['device_control:reboot'],
        'denied_permissions': ['testcases:delete']})
print(len(t['effective']), 'testcases:delete' in t['effective'])   # 34 False
PY
```

`tests/backend_server/test_permission_resolution.py` covers the same ground offline:

```bash
python3 -m pytest tests/backend_server/test_permission_resolution.py -q     # 20 passed
python3 -m pytest tests/backend_server -q -m unit                           # 111 passed
```

The parity test was checked against a deliberately reintroduced drift (the five strings deleted
again) and fails, so it is not vacuous.

`tests/backend_server/test_permissions.py` and `test_workspaces.py` cover the routes but drive a
live server on `:5109`; they were **not** run for this change. `test_workspaces.py` asserts that a
tester and a viewer are refused workspace management — still true after the decorator swap, since
neither holds `org.workspaces:*` — but that has not been confirmed against a running server.
