-- 20260520_add_rerun_payload_to_deployments.sql
-- Forward migration: add rerun_payload jsonb column to deployments so the
-- "Last Executions" rerun icon (RunTests.tsx) can relaunch a row without
-- refetching/recomputing the original launch config.
--
-- Apply with:
--   PGPASSWORD=$PGPASSWORD psql -h <db-vm> -p 54321 -U supabase_admin -d postgres \
--     -f setup/db/migrations/20260520_add_rerun_payload_to_deployments.sql
--   NOTIFY pgrst, 'reload schema';

ALTER TABLE deployments ADD COLUMN IF NOT EXISTS rerun_payload JSONB;

COMMENT ON COLUMN deployments.rerun_payload IS 'Full launch-time config for one-click rerun in "Last Executions" (RunTests.tsx). Discriminated by type: script/testcase/campaign. NULL means the row cannot be rerun via the icon.';
