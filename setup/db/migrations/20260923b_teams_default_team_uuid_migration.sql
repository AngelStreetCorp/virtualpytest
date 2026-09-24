-- 20260923b_teams_default_team_uuid_migration.sql
-- TASK-23 — Migrate the seeded Default Team from the legacy tenant UUID
-- (0000…001) to the canonical default tenant UUID (0000…000). The FK is
-- added in 20260923c; this migration just unifies the data so the FK has
-- a valid target.
--
-- Idempotent: re-runs are a no-op once 0000…001 is gone.

BEGIN;

UPDATE public.teams
SET    tenant_id = '00000000-0000-0000-0000-000000000000'
WHERE  tenant_id = '00000000-0000-0000-0000-000000000001';

COMMIT;