-- 20260908a_admin_profile_team_member_rpcs.sql
-- Forward migration: let the backend server read and write a SINGLE profile and
-- manage team membership, the same way it already reads ALL profiles.
--
-- Why: the server holds the Supabase ANON key and carries no user auth context, so
-- inside RLS `auth.uid()` is NULL and `public.is_admin()` is false. The profiles
-- policies from 20260907b are
--     SELECT / UPDATE  USING (auth.uid() = id OR public.is_admin())
-- and team_members INSERT/DELETE require is_admin() OR is_team_owner(). Every direct
-- table access the server makes against those tables therefore matches ZERO rows:
--   * GET  /server/users/<id>            -> 404 "User not found"  (for every user,
--                                           including real admins — BUG-0062)
--   * PUT  /server/users/<id>            -> 404, role/permission edits silently lost
--   * POST /server/teams/<id>/members    -> member never actually added
-- `get_all_users()` was unaffected only because 031_profiles_team_members_rpc.sql had
-- already routed the LIST around RLS via SECURITY DEFINER RPCs. These are the missing
-- single-row counterparts, same pattern, same justification.
--
-- Authorization has NOT been delegated to the database here: it lives in the routes,
-- which are admin-only as of BUG-0061 (require_admin_role). When TASK-10 moves the
-- server onto the service_role key these RPCs become redundant and should be dropped.
--
-- Apply with:
--   PGPASSWORD=$PGPASSWORD psql -h <db-vm> -p 54322 -U supabase_admin -d postgres \
--     -f setup/db/migrations/20260908a_admin_profile_team_member_rpcs.sql
--   NOTIFY pgrst, 'reload schema';

-- Update one profile from a JSONB patch. Only the six user-editable columns are
-- honoured; anything else in p_updates is ignored, so a caller cannot reach id,
-- created_at or any future column by accident.
CREATE OR REPLACE FUNCTION public.admin_update_profile(p_user_id UUID, p_updates JSONB)
RETURNS SETOF public.profiles
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  RETURN QUERY
  UPDATE public.profiles p SET
    full_name          = COALESCE(p_updates->>'full_name', p.full_name),
    avatar_url         = COALESCE(p_updates->>'avatar_url', p.avatar_url),
    role               = COALESCE(p_updates->>'role', p.role),
    team_id            = COALESCE((p_updates->>'team_id')::UUID, p.team_id),
    permissions        = COALESCE(p_updates->'permissions', p.permissions),
    denied_permissions = COALESCE(p_updates->'denied_permissions', p.denied_permissions),
    updated_at         = NOW()
  WHERE p.id = p_user_id
  RETURNING p.*;
END;
$$ LANGUAGE plpgsql VOLATILE;

COMMENT ON FUNCTION public.admin_update_profile(UUID, JSONB) IS
  'Server-side profile update that bypasses profiles RLS (server runs as anon). Route-level admin check is the authorization boundary. See 20260908a migration.';

-- Add a user to a team (idempotent: re-adding updates the membership role).
CREATE OR REPLACE FUNCTION public.admin_add_team_member(p_team_id UUID, p_user_id UUID, p_role TEXT DEFAULT 'member')
RETURNS SETOF public.team_members
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  RETURN QUERY
  INSERT INTO public.team_members (team_id, user_id, role, created_at, updated_at)
  VALUES (p_team_id, p_user_id, COALESCE(p_role, 'member'), NOW(), NOW())
  ON CONFLICT (team_id, user_id) DO UPDATE
    SET role = EXCLUDED.role, updated_at = NOW()
  RETURNING team_members.*;
END;
$$ LANGUAGE plpgsql VOLATILE;

COMMENT ON FUNCTION public.admin_add_team_member(UUID, UUID, TEXT) IS
  'Server-side team member add that bypasses team_members RLS (server runs as anon). See 20260908a migration.';

CREATE OR REPLACE FUNCTION public.admin_remove_team_member(p_team_id UUID, p_user_id UUID)
RETURNS INTEGER
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  removed INTEGER;
BEGIN
  DELETE FROM public.team_members
   WHERE team_id = p_team_id AND user_id = p_user_id;
  GET DIAGNOSTICS removed = ROW_COUNT;
  RETURN removed;
END;
$$ LANGUAGE plpgsql VOLATILE;

COMMENT ON FUNCTION public.admin_remove_team_member(UUID, UUID) IS
  'Server-side team member removal that bypasses team_members RLS (server runs as anon). See 20260908a migration.';

GRANT EXECUTE ON FUNCTION public.admin_update_profile(UUID, JSONB)          TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.admin_add_team_member(UUID, UUID, TEXT)    TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.admin_remove_team_member(UUID, UUID)       TO anon, authenticated, service_role;
