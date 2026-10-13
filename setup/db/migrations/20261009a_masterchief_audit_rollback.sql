-- TASK-71: rollback of 20261009a_masterchief_audit.sql.
-- Idempotent. Drops the policy first so REVOKE/table drop don't fail when the policy is missing.

BEGIN;

DROP POLICY IF EXISTS "service_role_all_masterchief_audit" ON public.masterchief_audit;
DROP TABLE IF EXISTS public.masterchief_audit;

COMMIT;
