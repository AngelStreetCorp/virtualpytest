-- 20261006a_ai_training_samples_retention_rollback.sql
-- Drops the training-sample retention added by 20261006a.
--
-- cleanup_all() is restored to EXACTLY the body that was live before 20261006a was applied:
-- the five members that existed in production, pinned to the same search_path. Only
-- cleanup_training_samples() is removed. Nothing else about the nightly job changes.
--
-- CORRECTION (2026-10-07): this file previously restored a cleanup_all() that called
-- retention.cleanup_execution_results(). That function was dropped on purpose by
-- 20260623_remove_execution_results_retention.sql (execution_results is NEVER deleted --
-- a 7-day window had already silently truncated the KPI dashboards). Calling a dropped
-- function makes every nightly run raise and abort. It is not restored here.
--
-- Idempotent: safe to re-run.

BEGIN;

DROP FUNCTION IF EXISTS retention.cleanup_training_samples();

CREATE OR REPLACE FUNCTION retention.cleanup_all()
RETURNS TABLE(
  deleted_count INTEGER,
  table_name TEXT,
  retention_days INTEGER,
  executed_at TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'retention', 'public', 'extensions'
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
  SELECT *, NOW() as executed_at FROM retention.cleanup_adhoc_deployment_receipts()
  UNION ALL
  SELECT *, NOW() as executed_at FROM retention.cleanup_quality_metrics();

  RAISE NOTICE '[retention] Completed scheduled cleanup at %', NOW();
END;
$$;

COMMIT;