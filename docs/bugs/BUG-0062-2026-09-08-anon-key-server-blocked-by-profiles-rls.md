# BUG-0062 — every single-user lookup 404'd: the server can't read `profiles` through RLS

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0062                                                                    |
| Reported  | 2026-09-08                                                                  |
| Status    | Fixed — superseded, see "Aftermath" (RLS half reverted; FK half is the real fix) |
| Severity  | High (user admin, role edits and team membership silently broken in the UI)  |
| Area      | shared/src/lib/database/{users,teams,workspaces}_db.py · setup/db/migrations/20260908a |
| Fixed in  | build 8713                                                                  |
| Commit    | this commit · 🗄 DB migration `20260908a_admin_profile_team_member_rpcs.sql` |

---

## Symptom

10 of the role-suite failures reported `{"error":"User not found"}` — all of them
`admin_can_*` tests, so this was never an authorization problem. Reproduced against the
live server with the service key, against **every** account:

```
GET /server/users -> 200, 7 users
test@test.com                    byId=404  perms=404
admin@example.com      byId=404  perms=404   <- a real admin account
user@example.com          byId=404  perms=404
admin.test@vpt.local             byId=404  perms=404
...
```

The list works; fetching any one of the users it just returned 404s. In the app that means
the Users page lists everyone but can open nobody, role and permission edits report "User
not found", and adding a member to a team reports success while adding nothing.

## Root cause

One cause, four symptoms: **the backend server holds the Supabase ANON key and carries no
user auth context**, so inside RLS `auth.uid()` is NULL and `public.is_admin()` is false.
The policies from `20260907b_studio_lint_hardening.sql` are:

```sql
-- profiles
FOR SELECT USING ((select auth.uid()) = id OR public.is_admin())
FOR UPDATE USING ((select auth.uid()) = id OR public.is_admin())
-- team_members
FOR INSERT WITH CHECK (public.is_admin() OR public.is_team_owner(team_id))
FOR DELETE USING      (public.is_admin() OR public.is_team_owner(team_id))
```

Every direct table access the server made against those tables matched **zero rows**:

| call | what it did | result |
|---|---|---|
| `users_db.get_user()` | `profiles.select().eq('id', …).single()` | None → 404 for all users |
| `users_db.update_user()` | `profiles.update()` | 0 rows → 404, edit lost |
| `teams_db.add_team_member()` | `team_members.insert()` | 0 rows, member never added |
| `teams_db.remove_team_member()` | `team_members.delete()` | 0 rows, returned `True` anyway |
| `workspaces_db.get_workspace_members()` | embedded `profiles(*)` | `None` → user members dropped |

`get_all_users()` was the only one that worked, and only because
`031_profiles_team_members_rpc.sql` had already routed the **list** around RLS via
`SECURITY DEFINER` RPCs. The single-row counterparts were never added, so the bug hid behind
a working list page.

## Fix

Migration `20260908a_admin_profile_team_member_rpcs.sql` adds the missing single-row RPCs,
same pattern and same justification as 031: `admin_update_profile(uuid, jsonb)`,
`admin_add_team_member(uuid, uuid, text)`, `admin_remove_team_member(uuid, uuid)`.
`admin_update_profile` honours only the six user-editable columns, so a caller cannot reach
`id`/`created_at` through the JSONB patch.

Code:

- `get_user()` is now `next(u for u in get_all_users() if u['id'] == user_id)`. That reuses
  the RPC path already known to work and, because both built the identical dict, removes the
  duplicated team-join logic — the single-user and list shapes can no longer drift.
- `update_user()`, `add_team_member()`, `remove_team_member()` call the new RPCs.
  `remove_team_member()` now returns the real row count instead of an unconditional `True`.
- `get_workspace_members()` resolves profile fields from `get_all_profiles()` and keys
  membership off `user_id` rather than the presence of the RLS-filtered embed.

**Authorization has not been delegated to the database.** It lives in the routes, which are
admin-only as of [BUG-0061](BUG-0061-2026-09-08-user-team-workspace-routes-had-no-role-check.md).
When TASK-10 moves the server onto the `service_role` key these RPCs become redundant and
should be dropped.

## Also fixed here

`test_translation.py` — two tests asserted route-specific wordings ("Host information
required", "host_name is required") that no longer exist. Every route resolves the host
through the one shared helper `route_utils.get_host_from_request()`, whose message is
`host_name required in request body or query parameters`, so both now assert on the durable
part of that contract: the error names the missing parameter.

## Not fixed here

`TestUC1RunnerCannotBuild::test_runner_cannot_create_campaign` and
`TestUC2ViewerCannotHide::test_viewer_cannot_delete_testcase` still fail. Both expect `403`
and get a `400` for a missing parameter, because `/server/campaigns/createCampaign` and
`/server/testcases/<id>` have **no permission enforcement at all** — no `@require_permission`
anywhere outside `server_auth_routes.py`. Their sibling tests only pass because they skip
(no `host_name` on the runner). Wiring `@require_permission` across the testcase, campaign
and execution routes is the PERMISSION_PLAN.md work proper: it decides what a tester or
viewer may do day to day, so it needs its own pass rather than being bolted onto a bug fix.


## Aftermath (2026-09-08, later the same day)

This was **two bugs wearing one coat**, and only half of the original diagnosis survived.

**Half 1 — RLS. Real, but no longer the mechanism.** TASK-10 moved the server and every host
onto `SUPABASE_SERVICE_ROLE_KEY`, which bypasses RLS outright, so the anon-key blackout
described above stopped applying. Migration `20260908b` drops the three RPCs added by
`20260908a`, and `users_db` / `teams_db` / `workspaces_db` are back on direct table access —
an RLS-bypassing function that nothing calls is pure attack surface. Kept from the reverted
change: `remove_team_member()` reports the real row count instead of always returning `True`.

**Half 2 — a missing foreign key. Still live, and the actual reason the lookup 404'd.**
Reverting to direct table access brought the 404 straight back, with a different error in the
server log:

```
[@db:users_db:get_user] Error: PGRST200
  Could not find a relationship between 'team_members' and 'teams' in the schema cache
```

`public.team_members` had `team_members_user_id_fkey` (`user_id → profiles.id`) and **nothing
on `team_id`**. So `team_members.select('team_id, teams(name, permissions)')` — exactly what
`get_user()` does — could never resolve, and there was no referential integrity on `team_id`
either: a membership could point at a team that did not exist, and deleting a team orphaned
its rows. `get_all_users()` had been immune only because `031` routed it through RPCs.

Migration `20260908c` adds `team_members_team_id_fkey ... ON DELETE CASCADE` (verified 0
orphan rows first). After it, by-id lookup is **8/8 → 200** and the full backend suite is
**550 passed, 67 skipped, 0 failed**.

The lesson worth keeping: the RLS explanation fitted every symptom and was independently
true, so it never got challenged. It just was not the only thing holding the lookup down.
