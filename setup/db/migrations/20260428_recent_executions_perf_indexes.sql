-- Performance indexes for /server/deployment/executions/recent
--
-- The endpoint does a fan-out of per-row lookups against script_results
-- (time-window fallback by team_id+script_name+host_name) and
-- campaign_executions (artifact resolution by metadata->>deployment_execution_id
-- and by team_id+host_name+device_name+started_at). Without composite indexes
-- these collapse to seq-scan on tables that grow with every script run, and on
-- the rpitest Pi that's a measurable fraction of the 7+s page latency we see
-- under polling load.
--
-- All indexes are CREATE … IF NOT EXISTS so this is safe to re-run.
-- CONCURRENTLY would be ideal but psql in a single transaction can't, and
-- these tables are small enough that a brief lock is fine.

-- 1) Per-row script_results fallback in flatten():
--      .eq('team_id').eq('script_name').eq('host_name').gte/lte('started_at')
CREATE INDEX IF NOT EXISTS idx_script_results_team_script_host_started
  ON script_results (team_id, script_name, host_name, started_at DESC);

-- 2) File-campaign artifact resolution in resolve_campaign_artifacts():
--      .eq('team_id').eq('host_name').eq('device_name').gte/lte('started_at')
CREATE INDEX IF NOT EXISTS idx_campaign_executions_team_host_device_started
  ON campaign_executions (team_id, host_name, device_name, started_at DESC);

-- 3) DB-campaign artifact resolution by metadata->>deployment_execution_id.
--    PostgREST's .contains('metadata', {...}) compiles to JSONB `@>`, which
--    needs a GIN index to avoid scanning the table.
CREATE INDEX IF NOT EXISTS idx_campaign_executions_metadata_gin
  ON campaign_executions USING gin (metadata jsonb_path_ops);

-- 4) deployment_history (and any other deployment_id+started_at order-by
--    in this file). idx_deployment_executions_deployment alone forces a
--    sort on top of the index scan.
CREATE INDEX IF NOT EXISTS idx_deployment_executions_deployment_started
  ON deployment_executions (deployment_id, started_at DESC);

ANALYZE script_results;
ANALYZE campaign_executions;
ANALYZE deployment_executions;
