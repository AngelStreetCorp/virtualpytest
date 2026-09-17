-- 20260915_profiles_provider_type_and_default_full_name.sql
-- Two provisioning defaults on public.profiles. Canonical definition:
-- setup/db/schema/018_supabase_auth_schema.sql. Idempotent: safe to re-run.
--
-- 1. provider_type — which platform the account came from. 'virtualpytest' for
--    anyone created here (UI signup, admin, our own tooling); an external system
--    provisioning over /server/users sends its own name (e.g. 'dmacp') so a row
--    says where the person is administered from. NOT NULL + DEFAULT, so every
--    existing row is backfilled to 'virtualpytest' by the ALTER itself.
--
-- 2. full_name defaults to the local part of the email (marie.dupont@x -> marie.dupont)
--    instead of NULL. Admin-created users carry no user_metadata at all, so every
--    provisioned account used to land with a blank name and show as an empty cell.

BEGIN;

ALTER TABLE public.profiles
  ADD COLUMN IF NOT EXISTS provider_type TEXT NOT NULL DEFAULT 'virtualpytest';

-- Blank is not a provider. Written as a trigger-free CHECK so a bad value fails
-- at the writer rather than becoming an unattributable row.
ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_provider_type_not_blank;
ALTER TABLE public.profiles
  ADD CONSTRAINT profiles_provider_type_not_blank CHECK (length(btrim(provider_type)) > 0);

COMMENT ON COLUMN public.profiles.provider_type IS
  'Platform this account is administered from. ''virtualpytest'' unless an external '
  'system set its own name when provisioning over /server/users.';

-- Existing rows with a blank full_name are deliberately left alone here: this migration
-- changes what happens from now on. Backfilling them is a separate, optional one-time
-- pass — 20260915b_profiles_backfill_blank_full_name.sql.

-- Same body as 018, with the full_name fallback appended to the COALESCE chain and
-- provider_type read from app metadata (the provisioning path stamps it there on
-- create; anything else is 'virtualpytest').
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

  -- Create profile with default team assignment
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
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, auth, extensions;

COMMIT;

-- get_all_profiles() is RETURNS SETOF profiles, so the new column flows through it
-- automatically — but PostgREST's schema cache and any cached plan still describe the
-- old row type until told otherwise ("cached plan must not change result type").
NOTIFY pgrst, 'reload schema';
