-- =====================================================
-- Migration: Add CHECK constraints on role columns
-- profiles.role must be 'admin' | 'tester' | 'viewer'
-- team_members.role must be 'owner' | 'admin' | 'member'
-- =====================================================

ALTER TABLE public.profiles
  DROP CONSTRAINT IF EXISTS profiles_role_check,
  ADD CONSTRAINT profiles_role_check CHECK (role IN ('admin', 'tester', 'viewer'));

ALTER TABLE public.team_members
  DROP CONSTRAINT IF EXISTS team_members_role_check,
  ADD CONSTRAINT team_members_role_check CHECK (role IN ('owner', 'admin', 'member'));
