-- =====================================================
-- Team Members Relationship Table
-- Links users (profiles) to teams with roles
-- =====================================================

-- Create team_members junction table
CREATE TABLE IF NOT EXISTS public.team_members (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  team_id UUID NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  role TEXT DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member')),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(team_id, user_id)  -- A user can only be in a team once
);

-- Add optional team_id to profiles for default/primary team
ALTER TABLE public.profiles 
ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES public.teams(id) ON DELETE SET NULL;

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_team_members_team_id ON public.team_members(team_id);
CREATE INDEX IF NOT EXISTS idx_team_members_user_id ON public.team_members(user_id);
CREATE INDEX IF NOT EXISTS idx_profiles_team_id ON public.profiles(team_id);

-- Enable Row Level Security
ALTER TABLE public.team_members ENABLE ROW LEVEL SECURITY;

-- RLS Policies for team_members
-- Allow users to view team members of teams they belong to
CREATE POLICY "Users can view team members of their teams"
  ON public.team_members
  FOR SELECT
  USING (
    auth.uid() IN (
      SELECT user_id FROM public.team_members WHERE team_id = team_members.team_id
    )
    OR
    auth.uid() IN (
      SELECT id FROM public.profiles WHERE role = 'admin'
    )
  );

-- Only admins and team owners can manage team members
CREATE POLICY "Admins and team owners can manage team members"
  ON public.team_members
  FOR ALL
  USING (
    auth.uid() IN (
      SELECT id FROM public.profiles WHERE role = 'admin'
    )
    OR
    auth.uid() IN (
      SELECT user_id FROM public.team_members 
      WHERE team_id = team_members.team_id AND role = 'owner'
    )
  );

-- Update profiles RLS — relies on public.is_admin() defined in 018_supabase_auth_schema.sql.
-- Re-asserted here (018 already creates the identical policies) so this file stays correct
-- on its own if 018's version of them ever changes; guarded since a fresh install already has
-- them from 018.
DROP POLICY IF EXISTS "Admins can view all profiles"   ON public.profiles;
DROP POLICY IF EXISTS "Admins can update all profiles" ON public.profiles;
DROP POLICY IF EXISTS "Users can view own profile"     ON public.profiles;
DROP POLICY IF EXISTS "Users can update own profile"   ON public.profiles;
DROP POLICY IF EXISTS "Users see own profile, admins see all"        ON public.profiles;
DROP POLICY IF EXISTS "Users update own profile, admins update all"  ON public.profiles;
CREATE POLICY "Users see own profile, admins see all"
  ON public.profiles FOR SELECT
  USING ((select auth.uid()) = id OR public.is_admin());
CREATE POLICY "Users update own profile, admins update all"
  ON public.profiles FOR UPDATE
  USING      ((select auth.uid()) = id OR public.is_admin())
  WITH CHECK ((select auth.uid()) = id OR public.is_admin());

-- Function to update updated_at timestamp for team_members
CREATE OR REPLACE FUNCTION public.handle_team_members_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to update updated_at on team_members changes
DROP TRIGGER IF EXISTS on_team_members_updated ON public.team_members;
CREATE TRIGGER on_team_members_updated
  BEFORE UPDATE ON public.team_members
  FOR EACH ROW EXECUTE FUNCTION public.handle_team_members_updated_at();

-- Function to get team member count
CREATE OR REPLACE FUNCTION public.get_team_member_count(team_uuid UUID)
RETURNS INTEGER AS $$
BEGIN
  RETURN (SELECT COUNT(*)::INTEGER FROM public.team_members WHERE team_id = team_uuid);
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON TABLE public.team_members IS 'Junction table linking users to teams with roles';
COMMENT ON COLUMN public.team_members.role IS 'User role within the team: owner, admin, or member';
COMMENT ON FUNCTION public.get_team_member_count IS 'Returns the number of members in a team';

