-- 20260923g_sync_user_claims_tenant_ids.sql
-- TASK-23 — Extend sync_user_claims_to_auth() to also sync tenant_ids
-- (from user_tenants) and is_platform_admin (from profiles) into the JWT's
-- app_metadata. The existing role/permissions/team_ids sync continues to live
-- here; the trigger wiring is unchanged from migration 20260917g.
--
-- Idempotent (CREATE OR REPLACE). After applying, every profile is backfilled
-- so existing JWTs pick up the new claims on the next refresh.

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
               '[]'::jsonb),
             'tenant_ids',         COALESCE(
               (SELECT jsonb_agg(tenant_id)
                FROM public.user_tenants WHERE user_id = p_user_id),
               '[]'::jsonb),
             'is_platform_admin',  COALESCE(p.is_platform_admin, false)
           )
  FROM public.profiles p
  WHERE p.id = u.id AND u.id = p_user_id;
END;
$$;

-- Backfill every account so existing JWTs pick up the new claims on next refresh.
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT id FROM public.profiles LOOP
    PERFORM public.sync_user_claims_to_auth(r.id);
  END LOOP;
END $$;