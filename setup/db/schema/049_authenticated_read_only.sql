-- =====================================================
-- Schema 049: the browser's role is read-only
-- =====================================================
-- TASK-22. Companion to 20260917c_authenticated_read_only.sql (same statements,
-- applied to an existing database). Keep the two in step.
--
-- TASK-10 closed the app tables to the public key but left `authenticated` with full
-- DML on the two tables the SPA reads — profiles and team_members — because the RLS
-- policies looked narrow enough. They are not: the profiles UPDATE policy is
-- `uid() = id OR is_admin()` with no column restriction, `authenticated` held UPDATE
-- on every column including `role`, and the on_profile_role_sync trigger copies
-- profiles.role into auth.users.raw_app_meta_data, where it becomes the JWT claim the
-- backend trusts (auth_middleware.py). So any logged-in user could PATCH their own
-- profile row over the public PostgREST endpoint and hold an admin token on the next
-- refresh. With open signup that is "anyone on the internet is an admin".
--
-- The SPA only ever SELECTs these tables (AuthContext.tsx: two reads plus
-- refreshProfile), so nothing in the product needs the write grants. Profile and
-- membership edits go through Flask on the service role, where @require_admin_role
-- already guards /server/users.
-- =====================================================

-- ---------------------------------------------------------------------------
-- 1. Take every write privilege off the browser's role
-- ---------------------------------------------------------------------------
-- TRUNCATE is listed deliberately: it is NOT subject to row level security, so an
-- RLS policy never constrained it. PostgREST does not expose it, which is the only
-- reason it was not reachable — not a boundary worth relying on.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
    ON public.profiles, public.team_members
    FROM authenticated;

-- anon should hold nothing at all on app tables (TASK-10); re-assert it here so a
-- fresh install and a migrated database end up identical.
REVOKE ALL ON public.profiles, public.team_members FROM anon;

-- The reads the SPA actually makes. Still filtered by the existing per-user RLS
-- policies ("Users see own profile, admins see all" / "Team members and admins can
-- view team members") — this grant does not widen what a row-level policy allows.
GRANT SELECT ON public.profiles, public.team_members TO authenticated;

-- ---------------------------------------------------------------------------
-- 2. Stop the next table from re-opening the hole
-- ---------------------------------------------------------------------------
-- Supabase ships ALTER DEFAULT PRIVILEGES granting ALL on new public tables to anon
-- and authenticated. That is what produced the 90-table anon surface TASK-10 had to
-- clean up, and it is still armed: a table created by the `postgres` role (Studio's
-- SQL editor, the Grafana datasource role, any migration not run as supabase_admin)
-- is born world-writable to every logged-in browser. Point-in-time REVOKEs cannot
-- hold while this is set.
--
-- Functions are left alone on purpose: EXECUTE for authenticated is how the browser
-- calls the RPCs it is supposed to call (TASK-10 kept those deliberately).
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    REVOKE ALL ON SEQUENCES FROM anon, authenticated;

-- service_role is BYPASSRLS and keeps everything — it is what the server and every
-- host authenticate as, and it is never shipped to a browser.
