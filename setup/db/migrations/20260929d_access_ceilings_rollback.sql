-- 20260929d_access_ceilings_rollback.sql
-- Inverse of 20260929d_access_ceilings.sql. Deploy the matching older code with it.
--
-- ⚠ Team ceilings become empty grant lists ('[]'): a team that had a ceiling grants nothing,
-- exactly like a team before the migration. Device ceilings are dropped. The team grant lists
-- reset by the migration are not restored (they were deliberately discarded).

BEGIN;

UPDATE public.teams SET permissions = '[]'::jsonb WHERE permissions IS NULL
    OR jsonb_typeof(permissions) = 'array';
ALTER TABLE public.teams ALTER COLUMN permissions SET DEFAULT '[]'::jsonb;

ALTER TABLE public.teams    DROP COLUMN IF EXISTS allowed_devices;
ALTER TABLE public.roles    DROP COLUMN IF EXISTS allowed_devices;
ALTER TABLE public.profiles DROP COLUMN IF EXISTS allowed_devices;

DROP TRIGGER IF EXISTS on_user_tenant_sync ON public.user_tenants;
DROP FUNCTION IF EXISTS public.sync_user_tenant_to_auth();

DROP TRIGGER IF EXISTS on_team_permissions_sync ON public.teams;
CREATE TRIGGER on_team_permissions_sync
  AFTER UPDATE OF permissions ON public.teams
  FOR EACH ROW EXECUTE FUNCTION public.sync_team_permissions_to_auth();

-- Claims back to additive team grants (the 20260925a shape, plus the tenant claims).
CREATE OR REPLACE FUNCTION public.sync_user_claims_to_auth(p_user_id UUID)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  UPDATE auth.users u
  SET raw_app_meta_data =
        (COALESCE(u.raw_app_meta_data, '{}'::jsonb) - 'team_ceiling')
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
             'team_permissions',   COALESCE(
               (SELECT jsonb_agg(DISTINCT perm)
                FROM public.teams tm
                CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(tm.permissions, '[]'::jsonb)) AS perm
                WHERE tm.id IN (SELECT p.team_id UNION
                                SELECT m.team_id FROM public.team_members m WHERE m.user_id = p.id)),
               '[]'::jsonb),
             'tenant_ids',         COALESCE(
               (SELECT jsonb_agg(ut.tenant_id) FROM public.user_tenants ut WHERE ut.user_id = p.id),
               '[]'::jsonb),
             'is_platform_admin',  COALESCE(p.is_platform_admin, false)
           )
  FROM public.profiles p
  WHERE p.id = u.id AND u.id = p_user_id;
END;
$$;

DROP FUNCTION IF EXISTS public.team_cap(UUID, TEXT);

DROP FUNCTION IF EXISTS public.get_user_team_memberships();
CREATE FUNCTION public.get_user_team_memberships()
RETURNS TABLE(user_id UUID, team_id UUID, team_name TEXT, team_permissions JSONB)
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  RETURN QUERY
    SELECT tm.user_id, tm.team_id, t.name AS team_name,
           COALESCE(t.permissions, '[]'::JSONB) AS team_permissions
    FROM public.team_members tm
    JOIN public.teams t ON t.id = tm.team_id
    ORDER BY tm.user_id, t.name;
END;
$$ LANGUAGE plpgsql STABLE;
REVOKE EXECUTE ON FUNCTION public.get_user_team_memberships() FROM PUBLIC, anon, authenticated;
GRANT  EXECUTE ON FUNCTION public.get_user_team_memberships() TO service_role;

UPDATE public.role_permissions r
SET permissions = COALESCE((
        SELECT jsonb_agg(p ORDER BY p) FROM jsonb_array_elements_text(r.permissions) AS p
        WHERE p NOT LIKE 'org.workspaces:%'), '[]'::jsonb)
WHERE r.role = 'manager';

DELETE FROM public.data_migrations WHERE name = '20260929d_access_ceilings';

DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT id FROM public.profiles LOOP
    PERFORM public.sync_user_claims_to_auth(r.id);
  END LOOP;
END $$;

COMMIT;

NOTIFY pgrst, 'reload schema';
