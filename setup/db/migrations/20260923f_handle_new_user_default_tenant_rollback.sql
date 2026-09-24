-- 20260923f_handle_new_user_default_tenant_rollback.sql
-- Inverse of 20260923f. Restores the pre-TASK-23 handle_new_user() that
-- picked the default team by is_default = true (no tenants / user_tenants
-- writes).
--
-- Captured from 192.168.0.102 on 2026-09-23 before the migration. Re-apply this
-- if you need to roll back to a state where handle_new_user does not touch
-- the tenants table.

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'auth', 'extensions'
AS $function$
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
    'viewer',
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
$function$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();