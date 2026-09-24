-- 20260923a_tenants_table_rollback.sql
-- Inverse of 20260923a_tenants_table.sql. Drops the tenants table and the
-- service_role policy. FKs from teams/user_tenants must be removed first
-- (run 20260923c_teams_tenant_fk_rollback.sql and 20260923e_user_tenants_table_rollback.sql
-- in that order) or Postgres will cascade-drop this anyway.
--
-- DESTRUCTIVE: drops the tenants table. Only run after you've reverted every
-- reference (teams FK, user_tenants FK, claim sync reads, app code).

BEGIN;

DROP TABLE IF EXISTS public.tenants CASCADE;

COMMIT;