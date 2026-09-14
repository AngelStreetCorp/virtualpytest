-- Add retention cleanup for ad-hoc deployment receipts
-- ------------------------------------------------------
-- Ad-hoc receipts are one-shot rows inserted by
-- backend_server/src/lib/utils/adhoc_execution.py whenever a script or
-- campaign is launched via "Run Now" / direct API / MCP. They share a
-- fingerprint: cron '0 0 1 1 *', max_executions=1, no start_date,
-- status='completed' at creation. Their only purpose is to carry
-- host/device/script_name context on the deployment_executions join,
-- so once the join row is beyond retention there is no reason to keep
-- them. They accumulate without bound and were pushing real scheduled
-- deployments past the PostgREST 1000-row cap on /server/deployment/list.
--
-- The FK deployment_executions.deployment_id has ON DELETE CASCADE
-- (setup/db/schema/011_deployments.sql:49), so deleting the deployment
-- atomically purges the execution history too.
--
-- Idempotent: CREATE OR REPLACE for the function, DROP+re-schedule for
-- the cron entry, and cleanup_all() is re-created to include the new
-- step alongside the existing retention jobs.

-- 1) Cleanup function ---------------------------------------------------

CREATE OR REPLACE FUNCTION retention.cleanup_adhoc_deployment_receipts()
RETURNS TABLE(
  deleted_count INTEGER,
  table_name TEXT,
  retention_days INTEGER
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_deleted_count INTEGER;
BEGIN
  DELETE FROM public.deployments
  WHERE cron_expression = '0 0 1 1 *'
    AND max_executions = 1
    AND start_date IS NULL
    AND status = 'completed'
    AND created_at < NOW() - INTERVAL '30 days';

  GET DIAGNOSTICS v_deleted_count = ROW_COUNT;

  RAISE NOTICE '[retention] Deleted % ad-hoc deployment receipts (30 day retention, cascades to deployment_executions)', v_deleted_count;

  RETURN QUERY SELECT v_deleted_count, 'deployments (adhoc)'::TEXT, 30;
END;
$$;

COMMENT ON FUNCTION retention.cleanup_adhoc_deployment_receipts() IS
  'Deletes ad-hoc "Run Now" deployment receipts older than 30 days. Fingerprint: cron=0 0 1 1 *, max_executions=1, start_date IS NULL, status=completed. Cascades to deployment_executions.';

GRANT EXECUTE ON FUNCTION retention.cleanup_adhoc_deployment_receipts() TO postgres, service_role;

-- 2) Re-create cleanup_all() to include the new step -------------------

CREATE OR REPLACE FUNCTION retention.cleanup_all()
RETURNS TABLE(
  deleted_count INTEGER,
  table_name TEXT,
  retention_days INTEGER,
  executed_at TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  RAISE NOTICE '[retention] Starting scheduled cleanup at %', NOW();

  RETURN QUERY
  SELECT *, NOW() as executed_at FROM retention.cleanup_system_device_metrics()
  UNION ALL
  SELECT *, NOW() as executed_at FROM retention.cleanup_system_metrics()
  UNION ALL
  SELECT *, NOW() as executed_at FROM retention.cleanup_alerts()
  UNION ALL
  SELECT *, NOW() as executed_at FROM retention.cleanup_execution_results()
  UNION ALL
  SELECT *, NOW() as executed_at FROM retention.cleanup_adhoc_deployment_receipts();

  RAISE NOTICE '[retention] Completed scheduled cleanup at %', NOW();
END;
$$;

COMMENT ON FUNCTION retention.cleanup_all() IS
  'Master function that runs all retention cleanup functions. Returns summary of deleted records. Scheduled to run daily at 2:00 AM UTC via pg_cron.';

-- 3) Extend the monitoring view ----------------------------------------

CREATE OR REPLACE VIEW retention.policy_summary AS
SELECT
  'system_device_metrics' AS table_name,
  'timestamp' AS timestamp_column,
  7 AS retention_days,
  COUNT(*) AS current_records,
  MIN(timestamp) AS oldest_record,
  MAX(timestamp) AS newest_record
FROM public.system_device_metrics
UNION ALL
SELECT
  'system_metrics',
  'timestamp',
  7,
  COUNT(*),
  MIN(timestamp),
  MAX(timestamp)
FROM public.system_metrics
UNION ALL
SELECT
  'alerts',
  'start_time',
  7,
  COUNT(*),
  MIN(start_time),
  MAX(start_time)
FROM public.alerts
UNION ALL
SELECT
  'execution_results',
  'executed_at',
  7,
  COUNT(*),
  MIN(executed_at),
  MAX(executed_at)
FROM public.execution_results
UNION ALL
SELECT
  'deployments (adhoc)',
  'created_at',
  30,
  COUNT(*),
  MIN(created_at),
  MAX(created_at)
FROM public.deployments
WHERE cron_expression = '0 0 1 1 *'
  AND max_executions = 1
  AND start_date IS NULL
  AND status = 'completed';

GRANT SELECT ON retention.policy_summary TO postgres, anon, authenticated, service_role;

-- 4) Verify the daily cron job is still in place ------------------------
-- The existing 014_retention_schema.sql schedules 'retention-cleanup-all'
-- at '0 2 * * *' which now includes the new step via cleanup_all(). No
-- new cron entry is required. If the job is missing on this DB, uncomment:
-- SELECT cron.schedule('retention-cleanup-all', '0 2 * * *', 'SELECT retention.cleanup_all();');
