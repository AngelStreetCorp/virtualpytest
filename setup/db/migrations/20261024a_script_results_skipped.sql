-- BUG-0756 (framework leg): a check that never ran because it was not configured
-- must not be counted as a failure by a campaign.
--
-- Adds one column. Additive and idempotent by construction:
--   ADD COLUMN IF NOT EXISTS ... NOT NULL DEFAULT false
-- never rewrites the existing rows (Postgres stores the default, not a table
-- rewrite), never changes an existing column, never drops anything. Applying
-- it twice is a no-op.
--
-- Apply order: this migration MUST be applied before the code that writes the
-- column is deployed (shared/src/lib/database/script_results_db.py).

BEGIN;

ALTER TABLE public.script_results
    ADD COLUMN IF NOT EXISTS skipped boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN public.script_results.skipped IS
    'true when the run never executed because it was not configured; such a row is not a failure';

COMMIT;
