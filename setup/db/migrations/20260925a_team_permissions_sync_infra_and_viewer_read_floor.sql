-- 20260925a_team_permissions_sync_infra_and_viewer_read_floor.sql
-- Backfill the team-permissions sync infrastructure on deployments that
-- pre-date 20260917h, and pin the viewer-role read floor at the Default Team
-- level so it lands without waiting on a code deploy.
--
-- Background
-- ----------
-- The auth-middleware resolution is:
--
--     ROLE_DEFAULT_PERMISSIONS.get(user_role, set())
--     | set(user_team_permissions)
--     | set(user_permissions)
--
-- `user_team_permissions` is read from `auth.users.raw_app_meta_data.team_permissions`,
-- which the `sync_user_claims_to_auth(p_user_id)` SECURITY DEFINER trigger writes
-- from `public.teams.permissions`. That trigger, the matching
-- `sync_team_permissions_to_auth()` and the `on_team_permissions_sync` trigger on
-- `public.teams` were introduced in 20260917h. Deployments whose DB was provisioned
-- before that migration (e.g. the cloud Supabase project pbkstycfuagmbwdlnqlf)
-- have only the older `sync_profile_role_to_auth()` trigger, which copies `role`
-- and nothing else — the JWT for a viewer reads
--
--     app_metadata = {"role": "viewer", "provider": "email", "providers": ["email"]}
--
-- which means every viewer-issued JWT hits the route code with empty
-- `user_team_permissions` and `user_permissions`. The viewer-role defaults in
-- ROLE_DEFAULT_PERMISSIONS are the only thing keeping them off 403, and those
-- defaults do not currently include `plugins.testrail:view` /
-- `plugins.jira:view` / `device_control:view` / … — a documented BUG-0154-adjacent
-- drift between the role-default copy and the route vocabulary.
--
-- This migration is the runtime-side half of the fix:
--   1. installs the missing sync functions + trigger (idempotent),
--   2. grants the viewer read verbs on the Default Team so every viewer in that
--      team inherits them via `team_permissions` (no code deploy required),
--   3. forces a re-sync of every profile so existing JWTs pick the grants up on
--      their next refresh.
--
-- The matching code-side fix (adding the same verbs to ROLE_DEFAULT_PERMISSIONS
-- so fresh installs and team-less viewers are covered too) is commit `49b053`
-- on `main`, landed but not yet deployed on Render. Both paths converge when
-- the Render backend rebuild lands.
--
-- Idempotent. Safe to run while the backend is serving — the sync function is
-- SECURITY DEFINER and only touches auth.users.raw_app_meta_data for the
-- profiles explicitly named.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. sync_user_claims_to_auth(p_user_id) — copy role + permissions +
--    denied_permissions + team_ids + team_permissions from public.profiles /
--    public.teams into auth.users.raw_app_meta_data. Idempotent definition;
--    matches 20260917h exactly.
-- ---------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------
-- 2. teams.permissions changed -> re-sync every member of that team.
-- ---------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------
-- 3. Pin the viewer-role read floor on the Default Team.
--
-- Until the Render backend rebuild picks up the matching code change
-- (`49b053`), a fresh viewer on a team with no `permissions` would 403 every
-- /server/integrations/* GET — the only thing the live backend has access to
-- is what the JWT's `team_permissions` claim says. Granting the read verbs at
-- the team level is the contract the admin UI should eventually drive (see
-- docs/agent/platform/USER_PERMISSION.md §11 — Teams tab in the Users page),
-- but for now this seeds the floor so existing viewers stop hitting 403.
--
-- The set is the union of:
--   - device_control:view                           (host card status, no buttons)
--   - plugins.testrail:view / jira / slack          (read configured status)
--   - plugins.grafana:view / langfuse:view
--
-- Write verbs (`*:manage`, `device_control:execute`, `:reboot`, `:restart_streams`)
-- are deliberately NOT granted; the viewer read-only floor on the route side
-- (`enforce_viewer_read_only()`) refuses any non-GET regardless of these grants,
-- and the frontend Dashboard hides the buttons for users without
-- `device_control:execute`.
-- ---------------------------------------------------------------------------
UPDATE public.teams
SET permissions = COALESCE(permissions, '[]'::jsonb)
                  || '[
                       "device_control:view",
                       "plugins.testrail:view",
                       "plugins.jira:view",
                       "plugins.slack:view",
                       "plugins.grafana:view",
                       "plugins.langfuse:view"
                     ]'::jsonb
WHERE is_default IS TRUE
  AND NOT (permissions ? 'plugins.testrail:view');

-- ---------------------------------------------------------------------------
-- 4. Re-sync every profile so existing JWTs pick the grants up on their next
-- refresh. The user must sign out and back in (or wait for the existing token
-- to expire) before the new claims are visible to the backend.
-- ---------------------------------------------------------------------------
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT id FROM public.profiles LOOP
    PERFORM public.sync_user_claims_to_auth(r.id);
  END LOOP;
END $$;

COMMIT;