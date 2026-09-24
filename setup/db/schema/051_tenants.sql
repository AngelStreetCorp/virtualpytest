-- =====================================================
-- Tenants (TASK-23)
--
-- First-class multi-tenant entity. The default tenant is seeded here with the
-- well-known UUID 00000000-0000-0000-0000-000000000000 so existing call sites
-- (teams_db.create_team, users_db._ensure_team) keep working unchanged.
--
-- This file supersedes the legacy `teams.tenant_id uuid NOT NULL` column with
-- no SQL default. The FK constraint teams_tenant_id_fkey is added at the
-- bottom of this file (after the tenants table exists).
-- =====================================================

CREATE TABLE IF NOT EXISTS public.tenants (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT NOT NULL CHECK (length(btrim(name)) > 0),
  slug        TEXT NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{0,62}$'),
  description TEXT,
  is_default  BOOLEAN NOT NULL DEFAULT false,
  created_by  UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- Per-tenant branding overrides (TASK-23 footer-logo follow-up, 20260923i).
  -- All nullable so existing tenants stay untouched; URL must be https:// so a
  -- typo can't silently turn the footer into mixed-content.
  footer_logo_url     TEXT,
  footer_logo_alt     TEXT,
  footer_text_color   TEXT
);

-- Exactly one row may be is_default = true. The partial unique index enforces
-- this at the DB layer so no application code is trusted for the invariant.
CREATE UNIQUE INDEX IF NOT EXISTS tenants_one_default
  ON public.tenants ((true)) WHERE is_default;

ALTER TABLE public.tenants
  DROP CONSTRAINT IF EXISTS tenants_footer_logo_url_https;
ALTER TABLE public.tenants
  ADD CONSTRAINT tenants_footer_logo_url_https
    CHECK (footer_logo_url IS NULL OR footer_logo_url ~* '^https://')
    NOT VALID;

ALTER TABLE public.tenants
  DROP CONSTRAINT IF EXISTS tenants_footer_text_color_hex;
ALTER TABLE public.tenants
  ADD CONSTRAINT tenants_footer_text_color_hex
    CHECK (footer_text_color IS NULL OR footer_text_color ~* '^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$')
    NOT VALID;

-- RLS: service_role only (consistent with the post-TASK-10 lockdown). Anonymous
-- and authenticated roles get nothing — authorization is enforced server-side
-- via the @require_platform_admin decorator.
ALTER TABLE public.tenants ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_all_tenants" ON public.tenants;
CREATE POLICY "service_role_all_tenants" ON public.tenants
  FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON public.tenants FROM anon, authenticated;

-- Seed the default tenant with the well-known UUID.
INSERT INTO public.tenants (id, name, slug, description, is_default)
VALUES ('00000000-0000-0000-0000-000000000000',
        'Default',
        'default',
        'Built-in tenant for open signups and pre-existing teams. Holds the Default Team.',
        true)
ON CONFLICT (id) DO NOTHING;

-- Multi-tenant user membership (TASK-23 Q2). One user can have N rows here,
-- granting them access to N tenants. Roles are reserved for a future
-- tenant-admin concept; only 'member' is assigned in v1.
CREATE TABLE IF NOT EXISTS public.user_tenants (
  user_id    UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  tenant_id  UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  role       TEXT NOT NULL DEFAULT 'member'
    CHECK (role IN ('owner', 'admin', 'member')),
  granted_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, tenant_id)
);

CREATE INDEX IF NOT EXISTS user_tenants_tenant_id_idx
  ON public.user_tenants(tenant_id);

ALTER TABLE public.user_tenants ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_all_user_tenants" ON public.user_tenants;
CREATE POLICY "service_role_all_user_tenants" ON public.user_tenants
  FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON public.user_tenants FROM anon, authenticated;

-- Migrate the seeded Default Team from the legacy tenant UUID (0000…001) to
-- the canonical default tenant UUID (0000…000) so the FK below has a valid
-- target. No-op on a fresh install (no team is on 0000…001 yet).
UPDATE public.teams
SET    tenant_id = '00000000-0000-0000-0000-000000000000'
WHERE  tenant_id = '00000000-0000-0000-0000-000000000001';

-- Add the FK from teams.tenant_id to tenants.id. ON DELETE RESTRICT prevents
-- silently dropping a tenant that still has teams (Q6 decision).
ALTER TABLE public.teams
  DROP CONSTRAINT IF EXISTS teams_tenant_id_fkey;

ALTER TABLE public.teams
  ADD CONSTRAINT teams_tenant_id_fkey
    FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE RESTRICT;

-- Backfill user_tenants from each user's home team. On a fresh install this is
-- a no-op (no profiles yet at this point); on an existing install it grants
-- every profile membership in the tenant of their current team.
INSERT INTO public.user_tenants (user_id, tenant_id, role)
SELECT p.id, t.tenant_id, 'member'
FROM   public.profiles p
JOIN   public.teams t ON t.id = p.team_id
ON CONFLICT (user_id, tenant_id) DO NOTHING;

-- Replace handle_new_user() with the TASK-23-aware version that reads the
-- default tenant from `tenants` (not from `teams.is_default` directly) and
-- inserts a user_tenants row for the new user.
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

-- Re-assert the trigger so it points at the (re-defined) handle_new_user.
-- The trigger name stays the same; only the function body changes.
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();