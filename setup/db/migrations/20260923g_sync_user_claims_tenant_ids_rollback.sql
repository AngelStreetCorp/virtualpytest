-- 20260923g_sync_user_claims_tenant_ids_rollback.sql
-- Inverse of 20260923g. Restores sync_user_claims_to_auth() to its pre-TASK-23
-- shape (role / permissions / denied_permissions / team_ids only) so JWTs stop
-- carrying tenant_ids and is_platform_admin claims.
--
-- Existing JWTs that already carry tenant_ids/is_platform_admin are unaffected
-- until the user's next token refresh. To clear claims already on tokens,
-- see /server/auth/refresh or wait for token expiry.

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

-- Re-sync every account so the claim sync table reflects the old shape.
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT id FROM public.profiles LOOP
    PERFORM public.sync_user_claims_to_auth(r.id);
  END LOOP;
END $$;