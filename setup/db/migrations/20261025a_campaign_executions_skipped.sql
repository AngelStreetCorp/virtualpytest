-- BUG-0898: a deployment that never started (device busy, device locked by another
-- owner, device queue full) must leave a campaign-level record that reads as
-- skipped, so the nightly report can tell "the night ran and found nothing" from
-- "the night never ran".
--
-- The skip is a FLAG, not a status. campaign_executions.status keeps its meaning
-- and its CHECK constraint (pending/running/completed/failed/cancelled/aborted) is
-- untouched: the live table rejects every other value. A night that never ran is a
-- cancelled night, and this column says that it was cancelled before it started.
--
-- Additive and idempotent by construction:
--   ADD COLUMN IF NOT EXISTS ... NOT NULL DEFAULT false
-- never rewrites the existing rows (Postgres stores the default, not a table
-- rewrite), never changes an existing column, never drops anything. Applying it
-- twice is a no-op.
--
-- Apply order: this migration MUST be applied before the code that writes the
-- column is deployed (backend_host/src/services/deployment_scheduler.py). Until
-- it is applied the writer falls back to the row metadata, so no skip record is
-- lost in the meantime.

BEGIN;

ALTER TABLE public.campaign_executions
    ADD COLUMN IF NOT EXISTS skipped boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN public.campaign_executions.skipped IS
    'true when the campaign never started because its deployment was skipped; such a row is not a failure';

COMMIT;
