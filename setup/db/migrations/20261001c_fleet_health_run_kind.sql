-- 20261001c_fleet_health_run_kind.sql
-- Fleet Health dashboard shows two snapshots side by side: the nightly 07:00 check
-- (vpt-fleet-health.timer, with AI analysis + markdown report) and a live check every
-- 10 minutes (vpt-fleet-health-live.timer). Tag each row with the run that wrote it.
-- Existing rows were all written by the nightly run.
--
-- Canonical twin: setup/db/schema/040_fleet_health.sql. Idempotent.
-- Inverse: 20261001c_fleet_health_run_kind_rollback.sql.

BEGIN;

ALTER TABLE public.fleet_health
    ADD COLUMN IF NOT EXISTS run_kind TEXT NOT NULL DEFAULT 'nightly';
ALTER TABLE public.fleet_health DROP CONSTRAINT IF EXISTS fleet_health_run_kind_check;
ALTER TABLE public.fleet_health ADD CONSTRAINT fleet_health_run_kind_check
    CHECK (run_kind IN ('nightly', 'live'));

CREATE INDEX IF NOT EXISTS idx_fleet_health_run_kind
    ON public.fleet_health (run_kind, generated_at DESC);

COMMENT ON COLUMN public.fleet_health.run_kind IS
    'nightly = daily 07:00 run (AI + report, kept as history); live = 10-minute run, pruned after 24h';

COMMIT;

NOTIFY pgrst, 'reload schema';
