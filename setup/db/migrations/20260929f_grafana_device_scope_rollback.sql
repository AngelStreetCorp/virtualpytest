-- 20260929f_grafana_device_scope_rollback.sql
-- Inverse of 20260929f_grafana_device_scope.sql. Re-import the dashboards from before the
-- device-scope transform first: scoped dashboards call these functions and would error.

BEGIN;
DROP FUNCTION IF EXISTS public.grafana_device_scope(TEXT, TEXT, TEXT);
DROP FUNCTION IF EXISTS public.grafana_user_workspaces(TEXT);
COMMIT;
