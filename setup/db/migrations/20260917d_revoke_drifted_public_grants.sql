-- 20260917d_revoke_drifted_public_grants.sql
-- TASK-22, follow-up to 20260917c. Canonical: setup/db/schema/050_revoke_drifted_public_grants.sql
--
-- 20260917c stopped NEW tables being born open. This closes the ones already born
-- that way. Found on node3 2026-09-17: public.userinterface_publishes carried full
-- INSERT/UPDATE/DELETE for **anon** — the key shipped in every browser, no login
-- needed — because it was created by the `postgres` role after TASK-10's cleanup and
-- inherited Supabase's default ACL. The main node has the same table with no such
-- grant, because there it was created by `supabase_admin`. Same schema, same release,
-- different creator, different exposure: which is exactly why this is a sweep over
-- whatever is actually there rather than a list of table names.
--
-- Idempotent and safe to re-run: a REVOKE of a privilege nobody holds is a no-op, so
-- on an already-clean database this changes nothing.
BEGIN;

-- 1. Take everything off both browser-facing roles, across every relation in public
--    (tables, partitioned tables, views, materialized views, foreign tables).
DO $$
DECLARE r record;
BEGIN
    FOR r IN
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r','p','v','m','f')
    LOOP
        EXECUTE format('REVOKE ALL ON public.%I FROM anon, authenticated', r.relname);
    END LOOP;
END $$;

-- 2. Put back the only reads a browser actually makes. AuthContext.tsx reads these two
--    and nothing else; both stay filtered by their existing per-user RLS policies.
GRANT SELECT ON public.profiles, public.team_members TO authenticated;

-- 3. The analytics_* views, where they exist. They are security_invoker, so a browser
--    reading them directly still sees nothing — the frontend gets this data through the
--    server on the service role. Granted only to keep a migrated database identical to
--    the main node rather than subtly different.
DO $$
DECLARE r record;
BEGIN
    FOR r IN
        SELECT viewname FROM pg_views
        WHERE schemaname = 'public' AND viewname LIKE 'analytics\_%'
    LOOP
        EXECUTE format('GRANT SELECT ON public.%I TO authenticated', r.viewname);
    END LOOP;
END $$;

COMMIT;
