-- 20260923e_user_tenants_table.sql
-- TASK-23 — Multi-tenant user membership (Q2 decision). One user can have N
-- rows here, granting them access to N tenants. Backfilled from each user's
-- home team so everyone keeps their current visibility.
--
-- Idempotent: CREATE IF NOT EXISTS, INSERT ON CONFLICT DO NOTHING.

BEGIN;

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

-- RLS: service_role only.
ALTER TABLE public.user_tenants ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_all_user_tenants" ON public.user_tenants;
CREATE POLICY "service_role_all_user_tenants" ON public.user_tenants
  FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON public.user_tenants FROM anon, authenticated;

-- Backfill from each user's home team. Users with no home team get no row —
-- that's the same visibility as before TASK-23 (no teams, nothing to see).
INSERT INTO public.user_tenants (user_id, tenant_id, role)
SELECT p.id, t.tenant_id, 'member'
FROM   public.profiles p
JOIN   public.teams t ON t.id = p.team_id
ON CONFLICT (user_id, tenant_id) DO NOTHING;

COMMIT;