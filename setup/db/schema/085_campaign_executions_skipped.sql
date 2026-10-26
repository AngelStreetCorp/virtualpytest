-- BUG-0898: a campaign whose deployment was skipped (device busy) is recorded as skipped, not left absent.
-- Mirrors setup/db/migrations/20261025a_campaign_executions_skipped.sql for fresh installs. Additive and idempotent.
ALTER TABLE campaign_executions
    ADD COLUMN IF NOT EXISTS skipped boolean NOT NULL DEFAULT false;
COMMENT ON COLUMN campaign_executions.skipped IS
    'true when the campaign never started because its deployment was skipped; such a row is not a failure';
