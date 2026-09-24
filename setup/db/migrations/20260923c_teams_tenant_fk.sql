-- 20260923c_teams_tenant_fk.sql
-- TASK-23 — Add the FK from teams.tenant_id to tenants.id, after both have
-- been seeded in 20260923a/b. ON DELETE RESTRICT prevents silently dropping a
-- tenant that still has teams (Q6 decision).
--
-- Will fail if any teams.tenant_id has no matching tenants.id (i.e. the UUID
-- migration in 20260923b didn't run or left orphans). Pre-flight query:
--   SELECT tenant_id, count(*) FROM public.teams GROUP BY tenant_id
--   HAVING tenant_id NOT IN (SELECT id FROM public.tenants);

BEGIN;

ALTER TABLE public.teams
  DROP CONSTRAINT IF EXISTS teams_tenant_id_fkey;

ALTER TABLE public.teams
  ADD CONSTRAINT teams_tenant_id_fkey
    FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE RESTRICT;

COMMIT;