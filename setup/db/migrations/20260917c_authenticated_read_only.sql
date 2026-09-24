-- 20260917c_authenticated_read_only.sql
-- TASK-22. Applies the read-only browser role to an existing database.
-- Canonical definition: setup/db/schema/049_authenticated_read_only.sql — keep the
-- two in step; this file is that one, applied to a database that already has data.
-- Idempotent: REVOKE/GRANT are safe to re-run.
--
-- Closes the self-promotion path: `authenticated` held UPDATE on every column of
-- public.profiles (including `role`) under the policy `uid() = id OR is_admin()`, and
-- on_profile_role_sync copies profiles.role into the JWT's app_metadata, which
-- auth_middleware.py trusts. Any logged-in user could PATCH themselves to admin.
-- Rollback: 20260917c_authenticated_read_only_rollback.sql
BEGIN;

REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
    ON public.profiles, public.team_members
    FROM authenticated;

REVOKE ALL ON public.profiles, public.team_members FROM anon;

GRANT SELECT ON public.profiles, public.team_members TO authenticated;

-- Supabase's default privileges grant ALL on every NEW public table to anon and
-- authenticated. Without this, the next table created by the `postgres` role (Studio
-- SQL editor, Grafana's datasource role, a migration not run as supabase_admin) is
-- born writable by every logged-in browser and TASK-10's cleanup silently decays.
-- Functions keep EXECUTE: that is how the browser reaches its intended RPCs.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    REVOKE ALL ON SEQUENCES FROM anon, authenticated;

COMMIT;
