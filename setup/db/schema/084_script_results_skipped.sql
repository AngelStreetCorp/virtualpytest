-- BUG-0756 (framework leg): a check that never ran because it was not configured is not a failure.
-- Mirrors setup/db/migrations/20261024a_script_results_skipped.sql for fresh installs. Additive and idempotent.
ALTER TABLE script_results
    ADD COLUMN IF NOT EXISTS skipped boolean NOT NULL DEFAULT false;
COMMENT ON COLUMN script_results.skipped IS
    'true when the run never executed because it was not configured; such a row is not a failure';
