-- =====================================================
-- Migration 029: Permission resolution RPC
-- Server-side function to compute effective permissions
-- =====================================================

-- Drop previous version if exists
DROP FUNCTION IF EXISTS public.get_user_effective_permissions(UUID);

-- Server-side helper to compute effective permissions for a user.
-- Resolution order:
--   ROLE_DEFAULTS (handled client/middleware side) UNION
--   all team permissions UNION
--   profile.permissions
--   MINUS profile.denied_permissions
--
-- NOTE: role defaults are NOT applied here — they are hardcoded in auth_middleware.py
-- and PermissionContext.tsx. This function only handles the DB-stored parts.
CREATE OR REPLACE FUNCTION public.get_user_effective_permissions(p_user_id UUID)
RETURNS JSONB AS $$
DECLARE
  v_profile      RECORD;
  v_team_perms   JSONB   := '[]'::jsonb;
  v_all_grants   JSONB;
  v_effective    JSONB;
BEGIN
  -- Load profile (role + explicit grants + denials)
  SELECT role, COALESCE(permissions, '[]'::jsonb) AS permissions,
         COALESCE(denied_permissions, '[]'::jsonb) AS denied_permissions
  INTO v_profile
  FROM public.profiles WHERE id = p_user_id;

  IF NOT FOUND THEN
    RETURN '[]'::jsonb;
  END IF;

  -- Collect all team permissions for every team the user belongs to
  SELECT COALESCE(jsonb_agg(DISTINCT elem), '[]'::jsonb)
  INTO v_team_perms
  FROM public.team_members tm
  JOIN public.teams t ON t.id = tm.team_id
  CROSS JOIN jsonb_array_elements_text(COALESCE(t.permissions, '[]'::jsonb)) AS elem
  WHERE tm.user_id = p_user_id;

  -- Union: profile.permissions + team permissions
  v_all_grants := v_profile.permissions || v_team_perms;

  -- Remove duplicates and subtract denied_permissions
  SELECT COALESCE(jsonb_agg(DISTINCT elem), '[]'::jsonb)
  INTO v_effective
  FROM jsonb_array_elements_text(v_all_grants) AS elem
  WHERE elem NOT IN (
    SELECT jsonb_array_elements_text(v_profile.denied_permissions)
  );

  RETURN COALESCE(v_effective, '[]'::jsonb);
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

-- Grant execute to authenticated users (RLS still applies on underlying tables)
GRANT EXECUTE ON FUNCTION public.get_user_effective_permissions(UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION public.get_user_effective_permissions(UUID) TO service_role;
