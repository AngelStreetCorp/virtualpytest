-- 20260908b_drop_admin_profile_rpcs.sql
-- Reverse migration: drop the three SECURITY DEFINER RPCs added by
-- 20260908a_admin_profile_team_member_rpcs.sql.
--
-- 20260908a existed for one reason: the backend server held the Supabase ANON key with no
-- user auth context, so `auth.uid()` was NULL and `public.is_admin()` false inside RLS, and
-- every direct read/write of profiles and team_members matched zero rows (BUG-0062). The
-- RPCs routed the single-row reads and writes around that.
--
-- TASK-10 has since moved the server (and every host) onto SUPABASE_SERVICE_ROLE_KEY, which
-- bypasses RLS outright — see supabase_utils.get_supabase_client(), which now prefers the
-- service key. The workaround is dead code, and an RLS-bypassing function that nothing calls
-- is pure attack surface: any holder of the anon key could still have invoked them to edit a
-- profile or team membership. So they go.
--
-- Apply with:
--   PGPASSWORD=$PGPASSWORD psql -h <db-vm> -p 54322 -U supabase_admin -d postgres \
--     -f setup/db/migrations/20260908b_drop_admin_profile_rpcs.sql
--   NOTIFY pgrst, 'reload schema';

DROP FUNCTION IF EXISTS public.admin_update_profile(UUID, JSONB);
DROP FUNCTION IF EXISTS public.admin_add_team_member(UUID, UUID, TEXT);
DROP FUNCTION IF EXISTS public.admin_remove_team_member(UUID, UUID);
