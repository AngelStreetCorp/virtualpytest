-- 20260923f_handle_new_user_default_tenant.sql
-- TASK-23 — Rewrite handle_new_user() so it reads the default tenant from
-- the tenants table (and inserts a user_tenants row), instead of relying on
-- the legacy path that picked the default team via is_default = true.
--
-- The trigger contract is unchanged: a new auth.users row produces a profile
-- with role = 'viewer', assigned to the default team, and (new) a row in
-- user_tenants for the default tenant.
--
-- Idempotent (CREATE OR REPLACE). The trigger itself is re-asserted so an
-- out-of-sync DB converges.

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
DECLARE
  v_default_tenant UUID;
  v_default_team   UUID;
BEGIN
  SELECT id INTO v_default_tenant FROM public.tenants WHERE is_default LIMIT 1;
  SELECT id INTO v_default_team
  FROM   public.teams
  WHERE  tenant_id = v_default_tenant AND is_default
  LIMIT  1;

  INSERT INTO public.profiles (id, email, full_name, avatar_url, role, team_id,
                               provider_type)
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
    v_default_team,
    COALESCE(NULLIF(btrim(NEW.raw_app_meta_data->>'provider_type'), ''), 'virtualpytest')
  );

  IF v_default_tenant IS NOT NULL THEN
    INSERT INTO public.user_tenants (user_id, tenant_id, role)
    VALUES (NEW.id, v_default_tenant, 'member')
    ON CONFLICT (user_id, tenant_id) DO NOTHING;
  END IF;

  IF v_default_team IS NOT NULL THEN
    INSERT INTO public.team_members (team_id, user_id, role)
    VALUES (v_default_team, NEW.id, 'member')
    ON CONFLICT (team_id, user_id) DO NOTHING;
  END IF;

  RETURN NEW;
END $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path TO 'public', 'auth', 'extensions';

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();