# BUG-0053 — Supabase Studio advisor: 5 security ERRORs and ~330 warnings on the production DB

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0053                                                     |
| Reported  | 2026-09-07                                                   |
| Status    | Fixed (applied on the production DB 2026-09-07)              |
| Severity  | Medium (5 ERROR-level definer views; rest is hardening/perf) |
| Area      | database / setup/db                                          |
| Fixed in  | build 8713                                                   |
| Commit    | see release note                                             |

---

## Symptom

After BUG-0052 cleared the "RLS disabled" items, Studio's **Security** and **Performance**
advisors (the open-source `splinter` lints, run directly with `psql` against 192.168.x.102)
still reported:

| Lint | Level | Before | After |
|---|---|---|---|
| Security Definer View | ERROR | 5 | **0** |
| Auth RLS Initialization Plan | WARN (perf) | 60 | **0** |
| Function Search Path Mutable | WARN | 50 | **0** |
| Multiple Permissive Policies | WARN (perf) | 18 | **0** |
| SECURITY DEFINER function executable by anon / authenticated | WARN | 25 + 25 | 11 + 11 |
| RLS Policy Always True | WARN | 21 | 76 (see below) |
| Unindexed foreign keys | INFO | 19 | 17 |
| Public / Signed-in can see object in GraphQL | WARN | 98 + 98 | 97 + 97 (unchanged) |
| Materialized View in API | WARN | 1 | 1 (unchanged) |
| Unused index | INFO | 224 | 218 (unchanged) |

## Root cause

- Five views (`device_info_corrected`, `device_info_key_status`, `gateway_info_corrected`,
  `gateway_info_key_status`, `edge_navigation_metrics`) were plain `CREATE VIEW`, which on
  Postgres defaults to running with the **owner's** privileges (`supabase_admin`), bypassing
  RLS of the underlying tables for whoever reads the view.
- The open policies were written as `(auth.uid() IS NULL) OR (auth.role() = ...) OR true`:
  always true, but calling `auth.*` **per row**.
- No function pinned `search_path`; every SECURITY DEFINER function (trigger functions
  included) was executable by `anon` because functions default to `EXECUTE` for `PUBLIC`.
- `profiles` had two SELECT and two UPDATE policies; `team_members` had a SELECT and a
  FOR ALL policy overlapping on SELECT. (`team_members` also had a much worse problem —
  see [BUG-0054](BUG-0054-2026-09-07-team-members-rls-infinite-recursion.md).)

## Fix

`setup/db/migrations/20260907b_studio_lint_hardening.sql` (idempotent; **applied on prod
2026-09-07** after a full dry run in a rolled-back transaction with anon / admin / member
probes):

- **A.** `ALTER VIEW … SET (security_invoker = on)` on the five views.
- **B.** `REVOKE EXECUTE … FROM PUBLIC, anon, authenticated` on 13 trigger functions
  (verified that triggers still fire — Postgres does not check EXECUTE at fire time) and 3
  RPCs with no caller in the codebase (`get_full_navigation_tree`, `get_tree_metrics_from_mv`,
  `get_user_effective_permissions`). The 11 that remain callable are the ones the backend
  calls with the anon key, plus `is_admin()` / `is_team_member()` / `is_team_owner()` which
  RLS policies evaluate as the calling role.
- **C.** `ALTER FUNCTION … SET search_path = public, auth, extensions` on the 50 functions
  (this is what the session default already resolved to, so no behaviour change).
- **D.** The 56 open policies rewritten as `USING (true)` — generated from `pg_policy`,
  preserving each policy's roles, command and WITH CHECK. This moves them from the
  performance tab ("initplan") to the security tab ("always true"); the latter is the
  documented platform model (authorization in the server layer, see `SERVER_AUTH.md`) and
  is the honest representation of what those policies do.
- **E.** `profiles`: one SELECT + one UPDATE policy (own row or admin) with
  `(select auth.uid())`. `team_members`: rebuilt on `is_team_member()` / `is_team_owner()`.
- **F.** Covering indexes on `deployment_executions.script_result_id` and
  `test_results.test_id` (the only FKs on tables with rows or a real join path).
- Also applied: the long-pending `20260425_drop_ai_userinterface_flows.sql`.

Folded into the schema: `018`, `019`, `025` (auth policies), `005`/`035`/`036`
(`security_invoker`), all `USING (…OR true)` blocks → `USING (true)`, and a new last file
`045_studio_lint_hardening.sql` (revokes, search_path, FK indexes).

## Left as-is, on purpose

- **pg_graphql exposure (194 WARN):** nothing in the repo uses GraphQL, but the extension is
  wired into two DDL event triggers (`graphql_watch_ddl/drop`); dropping it is a separate,
  deliberate change.
- **Materialized view in API:** `navigation_trees_db.py` reads `mv_full_navigation_trees`
  directly with the anon key; revoking would break it.
- **Unused indexes (218, 84 MB):** stats have never been reset, so the list is real, but it
  needs a usage review — not a blind drop.
- **17 unindexed FKs:** all on tables with ≤ 6 rows; adding indexes would only grow the
  unused-index list.
