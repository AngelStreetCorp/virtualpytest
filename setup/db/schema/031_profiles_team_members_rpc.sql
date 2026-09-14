-- Migration: Add SECURITY DEFINER RPC functions for profiles and team_members
-- These bypass RLS so the backend server (using anon key without auth context) can read data.
-- Same pattern as get_team_member_count() in 025_fix_team_members_rls.sql.

-- Get all profiles (bypasses RLS on profiles table)
CREATE OR REPLACE FUNCTION public.get_all_profiles()
RETURNS SETOF profiles
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  RETURN QUERY SELECT * FROM public.profiles ORDER BY created_at;
END;
$$ LANGUAGE plpgsql STABLE;

-- Get team members with joined profile data (bypasses RLS on team_members table)
CREATE OR REPLACE FUNCTION public.get_team_members_with_profiles(team_uuid UUID)
RETURNS TABLE(
  id UUID,
  user_id UUID,
  team_id UUID,
  role TEXT,
  created_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ,
  full_name TEXT,
  email TEXT,
  avatar_url TEXT,
  user_role TEXT
)
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  RETURN QUERY
    SELECT
      tm.id,
      tm.user_id,
      tm.team_id,
      tm.role,
      tm.created_at,
      tm.updated_at,
      COALESCE(p.full_name, '') AS full_name,
      COALESCE(p.email, '') AS email,
      p.avatar_url,
      COALESCE(p.role, 'viewer') AS user_role
    FROM public.team_members tm
    LEFT JOIN public.profiles p ON p.id = tm.user_id
    WHERE tm.team_id = team_uuid
    ORDER BY tm.created_at;
END;
$$ LANGUAGE plpgsql STABLE;

-- Get all user-team memberships with team names/permissions (for users list page)
CREATE OR REPLACE FUNCTION public.get_user_team_memberships()
RETURNS TABLE(
  user_id UUID,
  team_id UUID,
  team_name TEXT,
  team_permissions JSONB
)
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  RETURN QUERY
    SELECT
      tm.user_id,
      tm.team_id,
      t.name AS team_name,
      COALESCE(t.permissions, '[]'::JSONB) AS team_permissions
    FROM public.team_members tm
    JOIN public.teams t ON t.id = tm.team_id
    ORDER BY tm.user_id, t.name;
END;
$$ LANGUAGE plpgsql STABLE;
