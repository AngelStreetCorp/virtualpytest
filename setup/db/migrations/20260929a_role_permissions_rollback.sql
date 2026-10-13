-- 20260929a_role_permissions_rollback.sql
--
-- Reverts 20260929a_role_permissions.sql: drops the role_permissions table.
--
-- ⚠ Only together with a code rollback to a build that still hard-codes the role
-- defaults. Code that reads role_permissions resolves testers and viewers to no role
-- defaults once the table is gone. Any edits made on the Roles page are lost.

BEGIN;

DROP TABLE IF EXISTS public.role_permissions;

COMMIT;
