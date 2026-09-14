# BUG-0052 — Supabase Studio flags five public tables with RLS disabled

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0052                                                     |
| Reported  | 2026-09-07                                                   |
| Status    | Fixed (applied on the production DB 2026-09-07)              |
| Severity  | Low (lint/consistency; no change in effective access)        |
| Area      | database / setup/db                                          |
| Fixed in  | build 8713                                                   |
| Commit    | see release note                                             |

---

## Symptom

Supabase Studio's security advisor listed **"RLS Disabled in Public"** for five tables:
`ai_userinterface_tasks`, `ai_userinterface_transitions`, `ai_userinterface_verifications`,
`device_control_sessions`, `quality_metrics`. Every other `public` table showed clean.

## Root cause

The platform convention is: every table has RLS **enabled** with a single permissive
`FOR ALL TO public USING (true)` policy (the backend writes with the anon key, so a
restrictive policy would lock the server out; authorization is enforced in the Flask layer —
see `docs/agent/platform/SERVER_AUTH.md`).

These five tables reached the live DB through files that omitted that boilerplate:

- the three `ai_userinterface_*` tables were created by the incremental migration
  `20260424_ai_userinterface_pack_5layer.sql`, which only had `CREATE TABLE`. The canonical
  `033_ai_userinterface.sql` **does** carry the RLS block, so a fresh install was fine but the
  evolved production DB was not — classic schema/migration drift;
- `device_control_sessions` (`20260715_device_control_sessions.sql` and `039_*.sql`) and
  `quality_metrics` (`039_quality_metrics.sql`) never had the block anywhere.

Studio checks only whether RLS is *on*, not whether the policy restricts anything, so the
five tables were exactly as open as the other 75 — the warning was about consistency, not a
new exposure. `anon`/`authenticated` hold full DML grants on all of them either way.

## Fix

- `setup/db/migrations/20260907_enable_rls_missing_tables.sql` — idempotent: enables RLS and
  creates the standard open policy on the five tables. **Applied on 192.168.x.102 on
  2026-09-07**; verification query (any `public` table with RLS off *or* zero policies)
  returns 0 rows.
- Folded into `039_device_control_sessions.sql`, `039_quality_metrics.sql`,
  `20260424_ai_userinterface_pack_5layer.sql` and `20260715_device_control_sessions.sql`, so
  both fresh installs and replayed migrations produce the same state.
- Docs: `docs/get-started/supabase-setup.md` §4.1 no longer presents RLS as optional with a
  `auth.uid() = created_by` example (applying that would have broken the anon-writing
  server); it now states the actual model. `supabase-auth-setup.md` no longer claims app data
  is row-protected. `docs/agent/infra/DATABASE.md` documents the boilerplate every new table
  must carry.

## Also observed (not fixed here)

`ai_userinterface_flows` still exists on the production DB (0 rows) — migration
`20260425_drop_ai_userinterface_flows.sql` was never applied. Harmless; drop when convenient.

## How to check

```sql
SELECT c.relname, c.relrowsecurity,
       (SELECT count(*) FROM pg_policy p WHERE p.polrelid=c.oid) AS n_policies
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relkind IN ('r','p')
  AND (NOT c.relrowsecurity OR NOT EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid=c.oid));
-- expected: 0 rows
```
