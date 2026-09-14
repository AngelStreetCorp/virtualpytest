-- VirtualPyTest — dev/test/prod lifecycle for virtual scripts (existing DBs).
--
-- A virtual script name now has up to 3 live rows (one per environment). 'dev' is
-- canonical and always exists (editing writes it); 'test'/'prod' are promotion
-- snapshots created on Promote. On promote-to-prod the previous prod source is
-- snapshotted to virtual_scripts_history (via the existing BEFORE-UPDATE trigger)
-- as the N-1 rollback point, and virtual_scripts.prod_version increments.
--
-- Mirrors the testcase_definitions environment model. Canonical for fresh installs
-- is setup/db/schema/039_virtual_scripts.sql; this is the ALTER path for a DB that
-- already has the single-row-per-name virtual_scripts table.
--
-- Idempotent: safe to re-run. See docs/tasks/TASK-07-virtual-script-lifecycle.md.

-- 1. Columns -----------------------------------------------------------------
ALTER TABLE public.virtual_scripts
    ADD COLUMN IF NOT EXISTS environment VARCHAR(10) NOT NULL DEFAULT 'dev',
    ADD COLUMN IF NOT EXISTS prod_version INTEGER;

-- Backfill every pre-existing row to 'dev' (the DEFAULT already does this for the
-- ADD COLUMN, but be explicit for rows written between deploy steps).
UPDATE public.virtual_scripts SET environment = 'dev' WHERE environment IS NULL;

DO $$ BEGIN
    ALTER TABLE public.virtual_scripts
        ADD CONSTRAINT check_virtual_scripts_environment
        CHECK (environment IN ('dev', 'test', 'prod'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- 2. Uniqueness: one name per team PER ENVIRONMENT ---------------------------
-- Drop the old (team_id, name) unique constraint and replace with the 3-col one.
ALTER TABLE public.virtual_scripts
    DROP CONSTRAINT IF EXISTS unique_virtual_script_per_team;

DO $$ BEGIN
    ALTER TABLE public.virtual_scripts
        ADD CONSTRAINT unique_virtual_script_per_team_env
        UNIQUE (team_id, name, environment);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_virtual_scripts_environment
    ON public.virtual_scripts(environment);

COMMENT ON COLUMN public.virtual_scripts.environment IS
'Lifecycle env: dev (canonical, editable, always exists), test, or prod. A name fans out to <=3 rows.';
COMMENT ON COLUMN public.virtual_scripts.prod_version IS
'Prod row only: promote-to-prod counter (1=first). Previous prod source lives in _history as the N-1 rollback point.';
