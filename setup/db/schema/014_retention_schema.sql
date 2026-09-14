-- ================================================
-- Data Retention Schema and Policies
-- ================================================
-- Version: 1.0
-- Description: Automated data retention and cleanup system
-- Retention Period: 7 days for all time-series metrics tables
-- Schedule: Daily at 2:00 AM UTC
-- ================================================

-- Create the retention schema
CREATE SCHEMA IF NOT EXISTS retention;

COMMENT ON SCHEMA retention IS 
  'Contains functions and utilities for automatic data retention and cleanup policies';

-- ================================================
-- Cleanup Functions (7-day retention)
-- ================================================

-- 1. System Device Metrics Cleanup
CREATE OR REPLACE FUNCTION retention.cleanup_system_device_metrics()
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
  DELETE FROM public.system_device_metrics
  WHERE timestamp < NOW() - INTERVAL '365 days';
  
  GET DIAGNOSTICS v_deleted_count = ROW_COUNT;
  
  RAISE NOTICE '[retention] Deleted % records from system_device_metrics (365 day retention)', v_deleted_count;
  
  RETURN QUERY SELECT v_deleted_count, 'system_device_metrics'::TEXT, 365;
END;
$$;

COMMENT ON FUNCTION retention.cleanup_system_device_metrics() IS 
  'Deletes system_device_metrics records older than 365 days based on timestamp column';

-- 2. System Metrics Cleanup
CREATE OR REPLACE FUNCTION retention.cleanup_system_metrics()
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
  DELETE FROM public.system_metrics
  WHERE timestamp < NOW() - INTERVAL '365 days';
  
  GET DIAGNOSTICS v_deleted_count = ROW_COUNT;
  
  RAISE NOTICE '[retention] Deleted % records from system_metrics (365 day retention)', v_deleted_count;
  
  RETURN QUERY SELECT v_deleted_count, 'system_metrics'::TEXT, 365;
END;
$$;

COMMENT ON FUNCTION retention.cleanup_system_metrics() IS 
  'Deletes system_metrics records older than 365 days based on timestamp column';

-- 3. Alerts Cleanup
CREATE OR REPLACE FUNCTION retention.cleanup_alerts()
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
  DELETE FROM public.alerts
  WHERE start_time < NOW() - INTERVAL '7 days';
  
  GET DIAGNOSTICS v_deleted_count = ROW_COUNT;
  
  RAISE NOTICE '[retention] Deleted % records from alerts (7 day retention)', v_deleted_count;
  
  RETURN QUERY SELECT v_deleted_count, 'alerts'::TEXT, 7;
END;
$$;

COMMENT ON FUNCTION retention.cleanup_alerts() IS 
  'Deletes alerts records older than 7 days based on start_time column';

-- 5. Ad-hoc Deployment Receipts Cleanup
-- Ad-hoc receipts are one-shot rows inserted by backend_server/src/lib/utils/adhoc_execution.py
-- whenever a script or campaign is launched via "Run Now" / direct API / MCP. They share a
-- fingerprint: cron '0 0 1 1 *', max_executions=1, no start_date, created already status='completed'.
-- Their only purpose is to carry host/device/script_name context on the deployment_executions join,
-- so once the join row itself is beyond retention there is no reason to keep the deployment row.
-- The FK on deployment_executions.deployment_id is ON DELETE CASCADE (see 011_deployments.sql),
-- so this DELETE also purges the associated execution history rows atomically.
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

-- ================================================
-- Master Cleanup Function
-- ================================================

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
  SELECT *, NOW() as executed_at FROM retention.cleanup_adhoc_deployment_receipts();

  RAISE NOTICE '[retention] Completed scheduled cleanup at %', NOW();
END;
$$;

COMMENT ON FUNCTION retention.cleanup_all() IS 
  'Master function that runs all retention cleanup functions. Returns summary of deleted records. Scheduled to run daily at 2:00 AM UTC via pg_cron.';

-- ================================================
-- Retention Policy Summary View
-- ================================================

CREATE OR REPLACE VIEW retention.policy_summary AS
SELECT 
  'system_device_metrics' as table_name,
  'timestamp' as timestamp_column,
  365 as retention_days,
  COUNT(*) as current_records,
  MIN(timestamp) as oldest_record,
  MAX(timestamp) as newest_record
FROM public.system_device_metrics
UNION ALL
SELECT 
  'system_metrics',
  'timestamp',
  365,
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

COMMENT ON VIEW retention.policy_summary IS 
  'Summary view of all retention policies and current data status. Use this to monitor data age and record counts.';

-- ================================================
-- Schedule Automated Cleanup (pg_cron)
-- ================================================

-- Enable pg_cron extension
CREATE EXTENSION IF NOT EXISTS pg_cron;

-- Schedule master cleanup job (daily at 2:00 AM UTC)
SELECT cron.schedule(
  'retention-cleanup-all',
  '0 2 * * *',
  'SELECT retention.cleanup_all();'
);

-- ================================================
-- Permissions
-- ================================================

-- Grant usage on the schema
GRANT USAGE ON SCHEMA retention TO postgres, anon, authenticated, service_role;

-- Grant execute on cleanup functions (service_role only for security)
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA retention TO postgres, service_role;

-- Grant select on the summary view (all roles can monitor)
GRANT SELECT ON retention.policy_summary TO postgres, anon, authenticated, service_role;

-- ================================================
-- Usage Examples
-- ================================================

-- Monitor retention policies:
-- SELECT * FROM retention.policy_summary;

-- Manually run cleanup for all tables:
-- SELECT * FROM retention.cleanup_all();

-- Manually run cleanup for specific table:
-- SELECT * FROM retention.cleanup_system_metrics();

-- Check scheduled jobs:
-- SELECT * FROM cron.job WHERE jobname LIKE 'retention%';

-- View job execution history:
-- SELECT * FROM cron.job_run_details 
-- WHERE jobid = (SELECT jobid FROM cron.job WHERE jobname = 'retention-cleanup-all')
-- ORDER BY start_time DESC LIMIT 10;

-- Modify retention period (example: change to 14 days):
-- Just edit the INTERVAL in the cleanup function, e.g.:
-- DELETE FROM public.system_metrics
-- WHERE timestamp < NOW() - INTERVAL '14 days';

