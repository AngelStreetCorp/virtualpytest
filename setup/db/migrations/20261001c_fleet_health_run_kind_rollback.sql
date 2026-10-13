-- 20261001c_fleet_health_run_kind_rollback.sql
-- Inverse of 20261001c_fleet_health_run_kind.sql. Stop vpt-fleet-health-live.timer first,
-- then apply: live rows are deleted so the older dashboard does not mix them with nightly runs.

BEGIN;

DELETE FROM public.fleet_health WHERE run_kind = 'live';
DROP INDEX IF EXISTS public.idx_fleet_health_run_kind;
ALTER TABLE public.fleet_health DROP CONSTRAINT IF EXISTS fleet_health_run_kind_check;
ALTER TABLE public.fleet_health DROP COLUMN IF EXISTS run_kind;

COMMIT;

NOTIFY pgrst, 'reload schema';
