-- 040_quality_metrics_retention.sql
-- 7-day retention for the AVQ quality_metrics table, wired into retention.cleanup_all().
-- Mirrors retention.cleanup_system_device_metrics() in 014_retention_schema.sql.

CREATE OR REPLACE FUNCTION retention.cleanup_quality_metrics()
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
  DELETE FROM public.quality_metrics
  WHERE timestamp < NOW() - INTERVAL '7 days';

  GET DIAGNOSTICS v_deleted_count = ROW_COUNT;
  RAISE NOTICE '[retention] Deleted % records from quality_metrics (7 day retention)', v_deleted_count;
  RETURN QUERY SELECT v_deleted_count, 'quality_metrics'::TEXT, 7;
END;
$$;

-- Re-create cleanup_all() to include quality_metrics (keep existing members in sync
-- with 014_retention_schema.sql).
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
  SELECT *, NOW() as executed_at FROM retention.cleanup_adhoc_deployment_receipts()
  UNION ALL
  SELECT *, NOW() as executed_at FROM retention.cleanup_quality_metrics();

  RAISE NOTICE '[retention] Completed scheduled cleanup at %', NOW();
END;
$$;
