-- 20260923c_teams_tenant_fk_rollback.sql
-- Inverse of 20260923c. Drops the teams.tenant_id FK. The column stays
-- (NOT NULL is preserved). Useful only as part of a full TASK-23 rollback.

BEGIN;

ALTER TABLE public.teams
  DROP CONSTRAINT IF EXISTS teams_tenant_id_fkey;

COMMIT;