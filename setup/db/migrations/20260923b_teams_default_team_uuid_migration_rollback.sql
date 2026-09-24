-- 20260923b_teams_default_team_uuid_migration_rollback.sql
-- Inverse of 20260923b. Re-points the migrated team(s) back to the legacy
-- UUID 0000…001 so the pre-migration state is restored. Only valid if the
-- FK from teams.tenant_id to tenants.id has already been dropped (otherwise
-- 0000…001 has no tenant row to point to — see 20260923c_teams_tenant_fk_rollback.sql).

BEGIN;

UPDATE public.teams
SET    tenant_id = '00000000-0000-0000-0000-000000000001'
WHERE  tenant_id = '00000000-0000-0000-0000-000000000000'
  AND  name     = 'Default Team';

COMMIT;