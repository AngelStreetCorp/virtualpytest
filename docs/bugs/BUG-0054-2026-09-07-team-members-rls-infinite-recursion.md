# BUG-0054 — Every direct read of `team_members` failed with "infinite recursion detected in policy"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0054                                                     |
| Reported  | 2026-09-07                                                   |
| Status    | Fixed (applied on the production DB 2026-09-07)              |
| Severity  | Medium (silent: team permissions never applied in the UI)    |
| Area      | database / auth / frontend AuthContext                       |
| Fixed in  | build 8713                                                   |
| Commit    | see release note                                             |

---

## Symptom

Found while dry-running BUG-0053. On the production DB, as `anon` **or** as any signed-in
user:

```
SELECT count(*) FROM public.team_members;
ERROR:  infinite recursion detected in policy for relation "team_members"
```

`frontend/src/contexts/auth/AuthContext.tsx` reads `team_members` right after the profile to
build `team_permissions`, inside a `try {} catch {}` that comments "non-fatal — team
permissions just won't be applied". So the error never surfaced, and the union of team
permissions has been empty for every user since the policies were written. Everything that
went through the SECURITY DEFINER RPCs (`get_team_member_count`,
`get_team_members_with_profiles`, `get_user_team_memberships`) kept working, which is why the
Team pages looked fine.

## Root cause

Both `team_members` policies (`019_team_members.sql`, "fixed" in
`025_fix_team_members_rls.sql`) sub-selected `public.team_members` inside a policy **on**
`team_members`. Postgres applies the table's policies to that sub-select too, which
re-enters the same policy → recursion error. Aliasing the sub-select (`tm`), which is what
025 did, changes nothing; the only real fix in 025 was making the RPC SECURITY DEFINER.

## Fix

Part E of `setup/db/migrations/20260907b_studio_lint_hardening.sql`:

- two `SECURITY DEFINER` helpers, same pattern as `is_admin()`:
  `public.is_team_member(team_id)` and `public.is_team_owner(team_id)` (bypass RLS, pinned
  `search_path`, callable by anon/authenticated because policies run as the caller);
- policies rebuilt on them: SELECT = member of the team or admin; INSERT / UPDATE / DELETE =
  admin or team owner.

Verified in the dry run: an admin sees all 3 profiles and all 3 memberships; a non-admin
member sees 1 profile and the 3 members of their own team, and `DELETE` as that member
affects 0 rows. Folded into `025_fix_team_members_rls.sql`.

No frontend change is needed — the existing `team_members` query now returns rows.
