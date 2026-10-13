-- 054_access_ceilings.sql
-- Canonical fresh-install state of TASK-31 phases B and C: team permission ceilings, device
-- ceilings, and the complete claim sync (role, grants, denials, team_ids, team_ceiling,
-- tenant_ids, is_platform_admin) with its triggers. Existing databases get it from
-- setup/db/migrations/20260929d_access_ceilings.sql — this file is that migration, which is
-- idempotent and safe on an empty database.

BEGIN;

-- One-shot guard (created by 20260928d on existing databases; fresh installs need it here).
CREATE TABLE IF NOT EXISTS public.data_migrations (
    name text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.data_migrations ENABLE ROW LEVEL SECURITY;  -- service role only

-- --------------------------------------------------------------- columns
ALTER TABLE public.teams ALTER COLUMN permissions DROP NOT NULL;
ALTER TABLE public.teams ALTER COLUMN permissions SET DEFAULT NULL;
UPDATE public.teams SET permissions = NULL WHERE permissions IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM public.data_migrations WHERE name = '20260929d_access_ceilings');

COMMENT ON COLUMN public.teams.permissions IS
    'Permission CEILING of the team: NULL = no limit; a list = members hold nothing outside it '
    '(union across their non-default teams). Not a grant (TASK-31).';

ALTER TABLE public.teams    ADD COLUMN IF NOT EXISTS allowed_devices JSONB DEFAULT NULL;
ALTER TABLE public.roles    ADD COLUMN IF NOT EXISTS allowed_devices JSONB DEFAULT NULL;
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS allowed_devices JSONB DEFAULT NULL;

ALTER TABLE public.teams    DROP CONSTRAINT IF EXISTS teams_allowed_devices_is_array;
ALTER TABLE public.teams    ADD  CONSTRAINT teams_allowed_devices_is_array
    CHECK (allowed_devices IS NULL OR jsonb_typeof(allowed_devices) = 'array');
ALTER TABLE public.roles    DROP CONSTRAINT IF EXISTS roles_allowed_devices_is_array;
ALTER TABLE public.roles    ADD  CONSTRAINT roles_allowed_devices_is_array
    CHECK (allowed_devices IS NULL OR jsonb_typeof(allowed_devices) = 'array');
ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_allowed_devices_is_array;
ALTER TABLE public.profiles ADD  CONSTRAINT profiles_allowed_devices_is_array
    CHECK (allowed_devices IS NULL OR jsonb_typeof(allowed_devices) = 'array');

COMMENT ON COLUMN public.teams.allowed_devices IS
    'Device ceiling (host_name:device_id keys), NULL = all. A UI filter, not authorization.';
COMMENT ON COLUMN public.roles.allowed_devices IS
    'Device ceiling of the role (host_name:device_id keys), NULL = all. A UI filter.';
COMMENT ON COLUMN public.profiles.allowed_devices IS
    'Device ceiling of the user, within team ∩ role (host_name:device_id keys), NULL = all. A UI filter.';

-- ------------------------------------------------------------- team_cap()
-- The ceiling a user's teams put on `kind` ('permissions' | 'devices'): NULL = no limit.
-- Default teams count only when the user is in no other team (every account lands in one).
CREATE OR REPLACE FUNCTION public.team_cap(p_user_id UUID, p_kind TEXT)
RETURNS JSONB
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  WITH mine AS (
    SELECT CASE WHEN p_kind = 'devices' THEN t.allowed_devices ELSE t.permissions END AS cap,
           COALESCE(t.is_default, false) AS is_default
    FROM public.teams t
    WHERE t.id IN (SELECT pr.team_id FROM public.profiles pr
                   WHERE pr.id = p_user_id AND pr.team_id IS NOT NULL
                   UNION
                   SELECT m.team_id FROM public.team_members m WHERE m.user_id = p_user_id)
  ), counted AS (
    SELECT cap FROM mine
    WHERE NOT is_default OR NOT EXISTS (SELECT 1 FROM mine WHERE NOT is_default)
  )
  SELECT CASE
           WHEN NOT EXISTS (SELECT 1 FROM counted)
             OR EXISTS (SELECT 1 FROM counted WHERE cap IS NULL) THEN NULL
           ELSE (SELECT COALESCE(jsonb_agg(DISTINCT v ORDER BY v), '[]'::jsonb)
                 FROM counted, jsonb_array_elements_text(counted.cap) AS v)
         END;
$$;

-- ------------------------------------------------ sync_user_claims_to_auth
CREATE OR REPLACE FUNCTION public.sync_user_claims_to_auth(p_user_id UUID)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  UPDATE auth.users u
  SET raw_app_meta_data =
        (COALESCE(u.raw_app_meta_data, '{}'::jsonb) - 'team_permissions')
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
               '[]'::jsonb),
             'team_ceiling',       public.team_cap(p.id, 'permissions'),
             'tenant_ids',         COALESCE(
               (SELECT jsonb_agg(ut.tenant_id) FROM public.user_tenants ut WHERE ut.user_id = p.id),
               '[]'::jsonb),
             'is_platform_admin',  COALESCE(p.is_platform_admin, false)
           )
  FROM public.profiles p
  WHERE p.id = u.id AND u.id = p_user_id;
END;
$$;

-- profiles: role / grants / denials / home team / platform admin
CREATE OR REPLACE FUNCTION public.sync_profile_role_to_auth()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  PERFORM public.sync_user_claims_to_auth(NEW.id);
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_profile_role_sync ON public.profiles;
CREATE TRIGGER on_profile_role_sync
  AFTER INSERT OR UPDATE OF role, permissions, denied_permissions, team_id, is_platform_admin
  ON public.profiles
  FOR EACH ROW EXECUTE FUNCTION public.sync_profile_role_to_auth();

-- team_members: joining or leaving changes team_ids and the ceiling
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

-- teams: a ceiling edit, or a team becoming / ceasing to be the default, re-syncs its members
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
  AFTER UPDATE OF permissions, is_default ON public.teams
  FOR EACH ROW EXECUTE FUNCTION public.sync_team_permissions_to_auth();

-- user_tenants: tenant grants change tenant_ids
CREATE OR REPLACE FUNCTION public.sync_user_tenant_to_auth()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  PERFORM public.sync_user_claims_to_auth(COALESCE(NEW.user_id, OLD.user_id));
  RETURN COALESCE(NEW, OLD);
END;
$$;

DROP TRIGGER IF EXISTS on_user_tenant_sync ON public.user_tenants;
CREATE TRIGGER on_user_tenant_sync
  AFTER INSERT OR UPDATE OR DELETE ON public.user_tenants
  FOR EACH ROW EXECUTE FUNCTION public.sync_user_tenant_to_auth();

REVOKE EXECUTE ON FUNCTION public.team_cap(UUID, TEXT)                FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.sync_user_claims_to_auth(UUID)      FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.sync_profile_role_to_auth()        FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.sync_team_member_to_auth()         FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.sync_team_permissions_to_auth()    FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.sync_user_tenant_to_auth()         FROM PUBLIC, anon, authenticated;
GRANT  EXECUTE ON FUNCTION public.team_cap(UUID, TEXT)                TO service_role;

-- --------------------------------------------- get_user_team_memberships()
-- Same callers as before (users list page); now with the raw ceiling (NULL kept), whether the
-- team is a default one, and its device ceiling.
DROP FUNCTION IF EXISTS public.get_user_team_memberships();
CREATE FUNCTION public.get_user_team_memberships()
RETURNS TABLE(
  user_id UUID,
  team_id UUID,
  team_name TEXT,
  team_permissions JSONB,
  team_is_default BOOLEAN,
  team_allowed_devices JSONB
)
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  RETURN QUERY
    SELECT tm.user_id, tm.team_id, t.name, t.permissions,
           COALESCE(t.is_default, false), t.allowed_devices
    FROM public.team_members tm
    JOIN public.teams t ON t.id = tm.team_id
    ORDER BY tm.user_id, t.name;
END;
$$ LANGUAGE plpgsql STABLE;

REVOKE EXECUTE ON FUNCTION public.get_user_team_memberships() FROM PUBLIC, anon, authenticated;
GRANT  EXECUTE ON FUNCTION public.get_user_team_memberships() TO service_role;

-- ------------------------------------------------------- manager defaults
UPDATE public.role_permissions r
SET permissions = (
        SELECT jsonb_agg(DISTINCT p ORDER BY p)
        FROM (
            SELECT jsonb_array_elements_text(r.permissions) AS p
            UNION
            SELECT unnest(ARRAY['org.workspaces:view', 'org.workspaces:create',
                                'org.workspaces:edit', 'org.workspaces:manage_members'])
        ) AS merged
    ),
    updated_at = NOW()
WHERE r.role = 'manager'
  AND NOT EXISTS (SELECT 1 FROM public.data_migrations WHERE name = '20260929d_access_ceilings');

-- --------------------------------------------------------------- one-shot
INSERT INTO public.data_migrations (name) VALUES ('20260929d_access_ceilings')
ON CONFLICT (name) DO NOTHING;

-- Every account's claims in the new shape.
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT id FROM public.profiles LOOP
    PERFORM public.sync_user_claims_to_auth(r.id);
  END LOOP;
END $$;

COMMIT;

NOTIFY pgrst, 'reload schema';
