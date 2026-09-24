-- 20260917h_team_permissions_in_app_metadata.sql
-- TASK-22. **Run before deploying the matching code.**
--
-- `teams.permissions` is a documented feature — a permission granted to everyone in a
-- team — and it was summed into the effective set by GET /server/users/:id/permissions
-- and by the frontend PermissionContext, but `require_permission()` never read it. So a
-- team grant showed as held in the UI and the server still answered 403. Latent only
-- because every team carries '[]'; the first admin to use the feature would have hit it.
--
-- Adds `team_permissions` to app_metadata: the union of `teams.permissions` across every
-- team the user belongs to. Same channel as role/permissions/team_ids, so it costs no
-- database round trip and cannot be forged from the browser.
--
-- Note the third trigger: `teams.permissions` changing must re-sync *every member* of
-- that team, not just whoever edited it.
--
-- Idempotent.
BEGIN;

CREATE OR REPLACE FUNCTION public.sync_user_claims_to_auth(p_user_id UUID)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_team_ids jsonb;
  v_team_perms jsonb;
BEGIN
  SELECT COALESCE(jsonb_agg(DISTINCT t), '[]'::jsonb) INTO v_team_ids
  FROM (
    SELECT p.team_id AS t FROM public.profiles p WHERE p.id = p_user_id AND p.team_id IS NOT NULL
    UNION
    SELECT m.team_id FROM public.team_members m WHERE m.user_id = p_user_id
  ) s WHERE t IS NOT NULL;

  SELECT COALESCE(jsonb_agg(DISTINCT perm), '[]'::jsonb) INTO v_team_perms
  FROM public.teams tm
  CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(tm.permissions, '[]'::jsonb)) AS perm
  WHERE to_jsonb(tm.id::text) <@ v_team_ids OR tm.id::text IN (SELECT jsonb_array_elements_text(v_team_ids));

  UPDATE auth.users u
  SET raw_app_meta_data =
        COALESCE(u.raw_app_meta_data, '{}'::jsonb)
        || jsonb_build_object(
             'role',               p.role,
             'permissions',        COALESCE(p.permissions, '[]'::jsonb),
             'denied_permissions', COALESCE(p.denied_permissions, '[]'::jsonb),
             'team_ids',           v_team_ids,
             'team_permissions',   v_team_perms
           )
  FROM public.profiles p
  WHERE p.id = u.id AND u.id = p_user_id;
END;
$$;

-- teams.permissions changed -> re-sync every member of that team
CREATE OR REPLACE FUNCTION public.sync_team_permissions_to_auth()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT id AS uid FROM public.profiles WHERE team_id = NEW.id
    UNION
    SELECT user_id FROM public.team_members WHERE team_id = NEW.id
  LOOP
    PERFORM public.sync_user_claims_to_auth(r.uid);
  END LOOP;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_team_permissions_sync ON public.teams;
CREATE TRIGGER on_team_permissions_sync
  AFTER UPDATE OF permissions ON public.teams
  FOR EACH ROW EXECUTE FUNCTION public.sync_team_permissions_to_auth();

DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT id FROM public.profiles LOOP
    PERFORM public.sync_user_claims_to_auth(r.id);
  END LOOP;
END $$;

COMMIT;
