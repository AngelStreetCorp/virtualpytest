-- =====================================================
-- Migration 028: Fine-grained permissions expansion
-- Adds team-level permissions and user-level denied_permissions
-- =====================================================

-- Add team-level permissions column
ALTER TABLE public.teams
  ADD COLUMN IF NOT EXISTS permissions JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN public.teams.permissions IS
  'Array of permission strings (resource:action) granted to all team members';

-- Add explicit denials column to profiles
ALTER TABLE public.profiles
  ADD COLUMN IF NOT EXISTS denied_permissions JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN public.profiles.denied_permissions IS
  'Array of permission strings explicitly denied for this user (overrides role + team grants)';

-- Backfill defaults for existing rows
UPDATE public.teams SET permissions = '[]'::jsonb WHERE permissions IS NULL;
UPDATE public.profiles SET denied_permissions = '[]'::jsonb WHERE denied_permissions IS NULL;
