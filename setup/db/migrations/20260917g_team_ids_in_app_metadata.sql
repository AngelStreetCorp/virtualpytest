-- 20260917g_team_ids_in_app_metadata.sql
-- TASK-22. **Run before deploying the matching code.**
--
-- Puts the set of teams a user belongs to into app_metadata.team_ids, so the server can
-- check a request's team_id against the caller without a database round trip.
--
-- Why it is needed: 140 `/server/*` routes read team_id straight from request.args and
-- nothing validated it. Proven on the live system 2026-09-17 — a viewer belonging only to
-- Default Team read another team's script_results by changing one query parameter, HTTP
-- 200. `team_id` is the multi-tenancy boundary for ~45 tables, so that was a full
-- cross-tenant read, and a write for anyone above viewer.
--
-- The set is home team (profiles.team_id) ∪ every team_members row. Kept in sync by
-- triggers on BOTH tables — membership changes in team_members, not profiles, so a
-- profiles-only trigger would go stale the moment anyone is added to a second team.
--
-- Idempotent.
BEGIN;

CREATE OR REPLACE FUNCTION public.sync_user_claims_to_auth(p_user_id UUID)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  UPDATE auth.users u
  SET raw_app_meta_data =
        COALESCE(u.raw_app_meta_data, '{}'::jsonb)
        || jsonb_build_object(
             'role',               p.role,
             'permissions',        COALESCE(p.permissions, '[]'::jsonb),
             'denied_permissions', COALESCE(p.denied_permissions, '[]'::jsonb),
             'team_ids',           COALESCE(
               (SELECT jsonb_agg(DISTINCT t) FROM (
                  SELECT p.team_id AS t WHERE p.team_id IS NOT NULL
                  UNION
                  SELECT m.team_id FROM public.team_members m WHERE m.user_id = p.id
                ) s WHERE t IS NOT NULL),
               '[]'::jsonb)
           )
  FROM public.profiles p
  WHERE p.id = u.id AND u.id = p_user_id;
END;
$$;

-- profiles: role / permissions / denials / home team
CREATE OR REPLACE FUNCTION public.sync_profile_role_to_auth()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  PERFORM public.sync_user_claims_to_auth(NEW.id);
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_profile_role_sync ON public.profiles;
CREATE TRIGGER on_profile_role_sync
  AFTER INSERT OR UPDATE OF role, permissions, denied_permissions, team_id ON public.profiles
  FOR EACH ROW EXECUTE FUNCTION public.sync_profile_role_to_auth();

-- team_members: membership is what actually changes when someone joins or leaves
CREATE OR REPLACE FUNCTION public.sync_team_member_to_auth()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  PERFORM public.sync_user_claims_to_auth(COALESCE(NEW.user_id, OLD.user_id));
  RETURN COALESCE(NEW, OLD);
END;
$$;

DROP TRIGGER IF EXISTS on_team_member_sync ON public.team_members;
CREATE TRIGGER on_team_member_sync
  AFTER INSERT OR UPDATE OR DELETE ON public.team_members
  FOR EACH ROW EXECUTE FUNCTION public.sync_team_member_to_auth();

-- Backfill every account.
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT id FROM public.profiles LOOP
    PERFORM public.sync_user_claims_to_auth(r.id);
  END LOOP;
END $$;

COMMIT;
