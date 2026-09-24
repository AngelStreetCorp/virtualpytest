-- 20260923a_tenants_table.sql
-- TASK-23 — First-class tenant entity. Creates the `tenants` table and seeds the
-- built-in default tenant with the well-known UUID the rest of the codebase uses
-- as its tenant fallback. Idempotent.
--
-- Pre-state expected on the deployment database:
--   * 0 rows in public.tenants
--   * 0 rows with is_default=true anywhere (this is the only default)
--
-- See setup/db/migrations/20260923a_tenants_table_rollback.sql for the inverse.

BEGIN;

CREATE TABLE IF NOT EXISTS public.tenants (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT NOT NULL CHECK (length(btrim(name)) > 0),
  slug        TEXT NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{0,62}$'),
  description TEXT,
  is_default  BOOLEAN NOT NULL DEFAULT false,
  created_by  UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Exactly one row may be is_default = true.
CREATE UNIQUE INDEX IF NOT EXISTS tenants_one_default
  ON public.tenants ((true)) WHERE is_default;

-- RLS: service_role only (consistent with the post-TASK-10 lockdown). Anonymous
-- and authenticated roles get nothing — authorization is enforced server-side.
ALTER TABLE public.tenants ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_all_tenants" ON public.tenants;
CREATE POLICY "service_role_all_tenants" ON public.tenants
  FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON public.tenants FROM anon, authenticated;

-- Seed the default tenant with the well-known UUID so existing writers
-- (teams_db.create_team, users_db._ensure_team) keep working unchanged.
INSERT INTO public.tenants (id, name, slug, description, is_default)
VALUES ('00000000-0000-0000-0000-000000000000',
        'Default',
        'default',
        'Built-in tenant for open signups and pre-existing teams. Holds the Default Team.',
        true)
ON CONFLICT (id) DO NOTHING;

-- Belt-and-braces: refuse to leave the DB in a state with two default tenants.
DO $$
BEGIN
  IF (SELECT count(*) FROM public.tenants WHERE is_default) > 1 THEN
    RAISE EXCEPTION 'More than one row with is_default=true after seeding default tenant';
  END IF;
END $$;

COMMIT;
