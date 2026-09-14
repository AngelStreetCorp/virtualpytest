-- =====================================================
-- Fix: Team Members RLS Policy Infinite Recursion
-- =====================================================
-- Aliasing the sub-select (the original 2026-03 attempt) does NOT stop Postgres
-- from recursing into the policy of the same table; reads of team_members by
-- anon/authenticated kept failing until 2026-09-07 (BUG-0054). The policies
-- below use SECURITY DEFINER helpers instead.

-- team_members: the old policies sub-selected team_members inside a policy ON
-- team_members, which Postgres rejects with "infinite recursion detected in
-- policy" — every direct read of team_members by anon/authenticated has been
-- failing in production (the frontend swallowed the error, so team
-- permissions were never applied — BUG-0054). Membership checks now go through
-- SECURITY DEFINER helpers (same pattern as is_admin()), and the SELECT and
-- write policies no longer overlap.
CREATE OR REPLACE FUNCTION public.is_team_member(p_team_id uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (SELECT 1 FROM public.team_members WHERE team_id = p_team_id AND user_id = auth.uid());
$$;
CREATE OR REPLACE FUNCTION public.is_team_owner(p_team_id uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (SELECT 1 FROM public.team_members WHERE team_id = p_team_id AND user_id = auth.uid() AND role = 'owner');
$$;
COMMENT ON FUNCTION public.is_team_member(uuid) IS 'RLS helper: is the calling user a member of the team (bypasses RLS to avoid policy recursion)';
COMMENT ON FUNCTION public.is_team_owner(uuid)  IS 'RLS helper: is the calling user an owner of the team (bypasses RLS to avoid policy recursion)';

DROP POLICY IF EXISTS "Users can view team members of their teams"     ON public.team_members;
DROP POLICY IF EXISTS "Admins and team owners can manage team members" ON public.team_members;
DROP POLICY IF EXISTS "Team members and admins can view team members"  ON public.team_members;
DROP POLICY IF EXISTS "Admins and team owners can add team members"    ON public.team_members;
DROP POLICY IF EXISTS "Admins and team owners can update team members" ON public.team_members;
DROP POLICY IF EXISTS "Admins and team owners can remove team members" ON public.team_members;
CREATE POLICY "Team members and admins can view team members"
  ON public.team_members FOR SELECT
  USING (public.is_team_member(team_id) OR public.is_admin());
CREATE POLICY "Admins and team owners can add team members"
  ON public.team_members FOR INSERT
  WITH CHECK (public.is_admin() OR public.is_team_owner(team_id));
CREATE POLICY "Admins and team owners can update team members"
  ON public.team_members FOR UPDATE
  USING (public.is_admin() OR public.is_team_owner(team_id));
CREATE POLICY "Admins and team owners can remove team members"
  ON public.team_members FOR DELETE
  USING (public.is_admin() OR public.is_team_owner(team_id));

-- Fix the RPC function to bypass RLS using SECURITY DEFINER
DROP FUNCTION IF EXISTS public.get_team_member_count(UUID);

CREATE OR REPLACE FUNCTION public.get_team_member_count(team_uuid UUID)
RETURNS INTEGER SECURITY DEFINER SET search_path = public AS $$
BEGIN
  RETURN (SELECT COUNT(*)::INTEGER FROM public.team_members WHERE team_id = team_uuid);
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION public.get_team_member_count IS 'Returns the number of members in a team (fixed to bypass RLS)';
