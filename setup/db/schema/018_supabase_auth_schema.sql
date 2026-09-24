-- =====================================================
-- Supabase Authentication Schema
-- Run this in Supabase SQL Editor
-- =====================================================

-- Create profiles table
CREATE TABLE IF NOT EXISTS public.profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email TEXT,
  full_name TEXT,
  avatar_url TEXT,
  role TEXT DEFAULT 'viewer' CHECK (role IN ('admin', 'tester', 'viewer')),
  permissions JSONB DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- team_id: nullable (a profile can exist before being assigned to a team, per
-- handle_new_user()/sync_profile_role_to_auth() below, which only assign it when a
-- default team exists) — never NOT NULL, and SET NULL rather than CASCADE since deleting
-- a team must not delete the user's profile.
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES teams(id) ON DELETE SET NULL;

-- provider_type: which platform the account is administered from. 'virtualpytest' for
-- anyone created here; an external system provisioning over /server/users sends its own
-- name (e.g. 'dmacp'). NOT NULL + DEFAULT so no row is ever unattributable.
ALTER TABLE public.profiles
  ADD COLUMN IF NOT EXISTS provider_type TEXT NOT NULL DEFAULT 'virtualpytest';
ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_provider_type_not_blank;
ALTER TABLE public.profiles
  ADD CONSTRAINT profiles_provider_type_not_blank CHECK (length(btrim(provider_type)) > 0);

-- is_platform_admin: TASK-23. Marks the user as a super admin — the only role
-- that can see / manage tenants. Default false so no existing account is auto-
-- promoted. Promotion is DB-only in v1:
--   UPDATE public.profiles SET is_platform_admin = true WHERE email = …;
ALTER TABLE public.profiles
  ADD COLUMN IF NOT EXISTS is_platform_admin BOOLEAN NOT NULL DEFAULT false;

-- Enable Row Level Security
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

-- Drop existing policies to make this script idempotent
DROP POLICY IF EXISTS "Users can view own profile" ON public.profiles;
DROP POLICY IF EXISTS "Users can update own profile" ON public.profiles;
DROP POLICY IF EXISTS "Admins can view all profiles" ON public.profiles;
DROP POLICY IF EXISTS "Admins can update all profiles" ON public.profiles;
DROP POLICY IF EXISTS "Users can view own profile" ON public.profiles;
DROP POLICY IF EXISTS "Users can update own profile" ON public.profiles;

-- is_admin() bypasses RLS (SECURITY DEFINER) to avoid infinite recursion
CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  RETURN EXISTS (SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role = 'admin');
END;
$$;

-- One SELECT and one UPDATE policy: own row, or admin (via is_admin()).
-- Kept to exactly one permissive policy per command so Studio's
-- "multiple permissive policies" lint stays quiet; auth.uid() wrapped in
-- (select ...) so it is evaluated once per query, not per row.
DROP POLICY IF EXISTS "Users see own profile, admins see all"        ON public.profiles;
DROP POLICY IF EXISTS "Users update own profile, admins update all"  ON public.profiles;
CREATE POLICY "Users see own profile, admins see all"
  ON public.profiles FOR SELECT
  USING ((select auth.uid()) = id OR public.is_admin());
CREATE POLICY "Users update own profile, admins update all"
  ON public.profiles FOR UPDATE
  USING      ((select auth.uid()) = id OR public.is_admin())
  WITH CHECK ((select auth.uid()) = id OR public.is_admin());

-- Function to auto-create profile on signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
DECLARE
  default_team_id UUID;
BEGIN
  -- Get the default team ID
  SELECT id INTO default_team_id 
  FROM public.teams 
  WHERE is_default = true 
  LIMIT 1;
  
  -- Create profile with default team assignment.
  -- full_name falls back to the local part of the email (marie.dupont@x -> marie.dupont):
  -- admin-created users carry no user_metadata at all, so without it every provisioned
  -- account lands with a blank name.
  INSERT INTO public.profiles (id, email, full_name, avatar_url, role, team_id, provider_type)
  VALUES (
    NEW.id,
    NEW.email,
    COALESCE(
      NULLIF(btrim(NEW.raw_user_meta_data->>'full_name'), ''),
      NULLIF(btrim(NEW.raw_user_meta_data->>'name'), ''),
      NULLIF(split_part(COALESCE(NEW.email, ''), '@', 1), '')
    ),
    NEW.raw_user_meta_data->>'avatar_url',
    'viewer', -- Default role for new users
    default_team_id,
    COALESCE(NULLIF(btrim(NEW.raw_app_meta_data->>'provider_type'), ''), 'virtualpytest')
  );
  
  -- Add user to default team in team_members table
  IF default_team_id IS NOT NULL THEN
    INSERT INTO public.team_members (team_id, user_id, role)
    VALUES (default_team_id, NEW.id, 'member')
    ON CONFLICT (team_id, user_id) DO NOTHING;
  END IF;
  
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger to create profile on user signup
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION public.handle_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to update updated_at on profile changes
DROP TRIGGER IF EXISTS on_profile_updated ON public.profiles;
CREATE TRIGGER on_profile_updated
  BEFORE UPDATE ON public.profiles
  FOR EACH ROW EXECUTE FUNCTION public.handle_updated_at();

-- Keep auth.users.raw_app_meta_data.role in sync with profiles.role so the
-- role rides the JWT as the server-controlled `app_metadata` claim (read by
-- backend_server require_user_auth). NOT user_metadata — that is user-editable
-- and would allow self-escalation. SECURITY DEFINER so it can write auth.users.
-- See migration 20260519_sync_profile_role_to_app_metadata.sql.
CREATE OR REPLACE FUNCTION public.sync_profile_role_to_auth()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  UPDATE auth.users
  SET raw_app_meta_data =
        COALESCE(raw_app_meta_data, '{}'::jsonb)
        || jsonb_build_object('role', NEW.role)
  WHERE id = NEW.id;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_profile_role_sync ON public.profiles;
CREATE TRIGGER on_profile_role_sync
  AFTER INSERT OR UPDATE OF role ON public.profiles
  FOR EACH ROW EXECUTE FUNCTION public.sync_profile_role_to_auth();

-- =====================================================
-- Backfill: Create profiles for existing users
-- =====================================================
-- Run this if you had users BEFORE creating the trigger
DO $$
DECLARE
  default_team_id UUID;
BEGIN
  -- Get the default team ID
  SELECT id INTO default_team_id 
  FROM public.teams 
  WHERE is_default = true 
  LIMIT 1;
  
  -- Create profiles for existing users
  INSERT INTO public.profiles (id, email, full_name, avatar_url, role, permissions, team_id)
  SELECT 
    u.id,
    u.email,
    COALESCE(u.raw_user_meta_data->>'full_name', u.raw_user_meta_data->>'name'),
    u.raw_user_meta_data->>'avatar_url',
    'viewer',
    '[]'::jsonb,
    default_team_id
  FROM auth.users u
  LEFT JOIN public.profiles p ON u.id = p.id
  WHERE p.id IS NULL
  ON CONFLICT (id) DO NOTHING;
  
  -- Add existing users to default team in team_members table. Guarded by to_regclass
  -- because team_members is created by 019_team_members.sql — a later file — so on a
  -- fresh install this table doesn't exist yet (harmless: no users exist yet either).
  IF default_team_id IS NOT NULL AND to_regclass('public.team_members') IS NOT NULL THEN
    INSERT INTO public.team_members (team_id, user_id, role)
    SELECT default_team_id, id, 'member'
    FROM public.profiles
    WHERE team_id = default_team_id
    ON CONFLICT (team_id, user_id) DO NOTHING;
  END IF;
END $$;

-- =====================================================
-- Initial Admin User (OPTIONAL)
-- =====================================================
-- After you create your first user (sign up), run this to make yourself admin:
-- UPDATE public.profiles SET role = 'admin' WHERE email = 'your-email@example.com';

