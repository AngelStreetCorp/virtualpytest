-- 20260907d_deployments_virtual_script_id.sql
-- Forward migration: let a deployment (scheduled run, multi-script batch run,
-- or a run queued because its device was locked) target a specific virtual
-- script row instead of only a disk script filename.
--
-- Without this, deployment_scheduler.py's `dep.get('virtual_script_id')` (it
-- already knows how to materialize + run a virtual script row — see
-- backend_host/src/services/deployment_scheduler.py) always read None, so any
-- virtual script routed through the deployment scheduler (locked-device
-- queueing, multi-script batch run, or a scheduled/planned run) either ran the
-- wrong dev/test/prod row or was misclassified as a DB campaign.
--
-- Apply with:
--   PGPASSWORD=$PGPASSWORD psql -h <db-vm> -p 54321 -U supabase_admin -d postgres \
--     -f setup/db/migrations/20260907d_deployments_virtual_script_id.sql
--   NOTIFY pgrst, 'reload schema';

ALTER TABLE deployments ADD COLUMN IF NOT EXISTS virtual_script_id UUID;
ALTER TABLE deployments ADD COLUMN IF NOT EXISTS environment VARCHAR(10) DEFAULT 'prod';

DO $$ BEGIN
    ALTER TABLE deployments
        ADD CONSTRAINT deployments_environment_check
        CHECK (environment IN ('dev', 'test', 'prod'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

UPDATE deployments SET environment = 'prod' WHERE environment IS NULL;

COMMENT ON COLUMN deployments.virtual_script_id IS 'Virtual-script deployments: which dev/test/prod row (virtual_scripts.id) to materialize and run. NULL for disk-script/campaign deployments.';
COMMENT ON COLUMN deployments.environment IS 'Capacity/KPI tag this run counts as (dev/test/prod). Mirrors script_results.environment.';
