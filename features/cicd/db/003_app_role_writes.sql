-- CI/CD feature — let the VPT server actually write (TASK-06 W11 follow-up).
--
-- 001/002 granted the app roles SELECT only, on the assumption stated in 001 that "the VPT
-- server (service_role) reads and writes". That assumption is wrong for this deployment:
-- `shared/src/lib/utils/supabase_utils.get_supabase_client()` — the client every feature and
-- core route uses — authenticates with **SUPABASE_ANON_KEY**, and the server's .env carries
-- only SUPABASE_URL / SUPABASE_ANON_KEY / SUPABASE_DB_URI / SUPABASE_JWT_SECRET. There is no
-- SUPABASE_SERVICE_ROLE_KEY, so `get_supabase_admin()` returns None in production.
--
-- Found by dispatching a real run through the deployed API on 2026-09-03: reads worked and
-- POST /server/cicd/dispatch failed with
--   {'message': 'permission denied for table ci_dispatches', 'code': '42501'}
--
-- Granting the app roles write access matches how every other table in this system already
-- works, and is not a downgrade relative to it: `public.script_results` grants anon the full
-- DELETE/INSERT/UPDATE set, and its RLS policy is
--   ((uid() IS NULL) OR (role() = 'service_role') OR true)
-- which ends in `OR true`, i.e. permissive. The API layer is what actually gates writes here:
-- /dispatch requires a signed-in user, /projects PUT requires the admin role, and /ingest
-- carries its own bearer token.
--
-- DELETE is deliberately NOT granted: nothing in the feature deletes rows.
--
-- Apply as supabase_admin (idempotent):
--   psql -h 127.0.0.1 -p 54322 -U supabase_admin -d postgres -f 003_app_role_writes.sql

\set ON_ERROR_STOP on

GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA cicd TO anon, authenticated;

-- ci_dispatches.id is a bigserial: inserting needs the sequence too.
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA cicd TO anon, authenticated;

-- Same for anything added to the schema later.
ALTER DEFAULT PRIVILEGES FOR ROLE cicd IN SCHEMA cicd
  GRANT SELECT, INSERT, UPDATE ON TABLES TO anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE cicd IN SCHEMA cicd
  GRANT USAGE, SELECT ON SEQUENCES TO anon, authenticated;

NOTIFY pgrst, 'reload schema';
