-- 20260623_remove_execution_results_retention.sql
--
-- Retention policy correction. The daily 02:00 pg_cron job (retention.cleanup_all)
-- deleted EVERY table on a 7-day window, including execution_results -- which
-- silently truncated the KPI dashboards (radar + Details) to the last ~7 days even
-- though the kpi_measurement scripts had been running all month.
--
-- New policy:
--   * execution_results (KPI measurements)  -> NEVER deleted (kept indefinitely)
--   * system_device_metrics                 -> 7  -> 365 days
--   * system_metrics                        -> 7  -> 365 days
--   * alerts                                -> 7 days   (unchanged)
--   * quality_metrics                       -> 7 days   (unchanged, if present)
--   * adhoc deployment receipts             -> 30 days  (unchanged, if present)
--
-- Resilient by design: cleanup_all() and policy_summary are rebuilt DYNAMICALLY
-- from whatever retention.cleanup_* functions / public tables actually exist, so
-- this runs cleanly on bases that don't have quality_metrics (or adhoc) yet.
--
-- Deletes no rows itself; only changes future cleanup behaviour.
-- Folded into setup/db/schema/014_retention_schema.sql for fresh installs.
-- NOTE: execution_results rows already purged before the last nightly run are
-- gone and cannot be recovered; history accumulates from now on.

BEGIN;

-- 1) Bump metrics retention to 365 days (only if the table exists). ----------
DO $mig$
BEGIN
  IF to_regclass('public.system_device_metrics') IS NOT NULL THEN
    EXECUTE $fn$
      CREATE OR REPLACE FUNCTION retention.cleanup_system_device_metrics()
      RETURNS TABLE(deleted_count INTEGER, table_name TEXT, retention_days INTEGER)
      LANGUAGE plpgsql SECURITY DEFINER AS $body$
      DECLARE v_deleted_count INTEGER;
      BEGIN
        DELETE FROM public.system_device_metrics WHERE timestamp < NOW() - INTERVAL '365 days';
        GET DIAGNOSTICS v_deleted_count = ROW_COUNT;
        RAISE NOTICE '[retention] Deleted % records from system_device_metrics (365 day retention)', v_deleted_count;
        RETURN QUERY SELECT v_deleted_count, 'system_device_metrics'::TEXT, 365;
      END;
      $body$;
    $fn$;
  END IF;

  IF to_regclass('public.system_metrics') IS NOT NULL THEN
    EXECUTE $fn$
      CREATE OR REPLACE FUNCTION retention.cleanup_system_metrics()
      RETURNS TABLE(deleted_count INTEGER, table_name TEXT, retention_days INTEGER)
      LANGUAGE plpgsql SECURITY DEFINER AS $body$
      DECLARE v_deleted_count INTEGER;
      BEGIN
        DELETE FROM public.system_metrics WHERE timestamp < NOW() - INTERVAL '365 days';
        GET DIAGNOSTICS v_deleted_count = ROW_COUNT;
        RAISE NOTICE '[retention] Deleted % records from system_metrics (365 day retention)', v_deleted_count;
        RETURN QUERY SELECT v_deleted_count, 'system_metrics'::TEXT, 365;
      END;
      $body$;
    $fn$;
  END IF;
END
$mig$;

-- 2) Rebuild cleanup_all() from the retention.cleanup_* functions that exist,
--    excluding the (now removed) execution_results cleanup. ------------------
DO $mig$
DECLARE
  v_branches TEXT;
  v_sql TEXT;
BEGIN
  SELECT string_agg(
           'SELECT *, NOW() AS executed_at FROM retention.' || quote_ident(p.proname) || '()',
           E'\n  UNION ALL\n  ' ORDER BY p.proname)
    INTO v_branches
  FROM pg_proc p
  JOIN pg_namespace n ON p.pronamespace = n.oid
  WHERE n.nspname = 'retention'
    AND p.proname LIKE 'cleanup%'
    AND p.proname NOT IN ('cleanup_all', 'cleanup_execution_results');

  IF v_branches IS NULL THEN
    v_branches := 'SELECT 0, ''(none)'', 0, NOW()';
  END IF;

  v_sql :=
    'CREATE OR REPLACE FUNCTION retention.cleanup_all() '
    || 'RETURNS TABLE(deleted_count INTEGER, table_name TEXT, retention_days INTEGER, executed_at TIMESTAMPTZ) '
    || 'LANGUAGE plpgsql SECURITY DEFINER AS $cab$ BEGIN '
    || 'RAISE NOTICE ''[retention] Starting scheduled cleanup at %'', NOW(); '
    || 'RETURN QUERY ' || v_branches || '; '
    || 'RAISE NOTICE ''[retention] Completed scheduled cleanup at %'', NOW(); '
    || 'END; $cab$;';
  EXECUTE v_sql;
END
$mig$;

-- 3) Drop the execution_results cleanup (cleanup_all no longer references it).
DROP FUNCTION IF EXISTS retention.cleanup_execution_results();

-- 4) Rebuild the summary view from tables that exist (skips missing ones). ---
DO $mig$
DECLARE
  v_parts TEXT[] := ARRAY[]::TEXT[];
  v_sql TEXT;
BEGIN
  IF to_regclass('public.system_device_metrics') IS NOT NULL THEN
    v_parts := array_append(v_parts, $b$SELECT 'system_device_metrics' AS table_name, 'timestamp' AS timestamp_column, 365 AS retention_days, COUNT(*) AS current_records, MIN(timestamp) AS oldest_record, MAX(timestamp) AS newest_record FROM public.system_device_metrics$b$);
  END IF;
  IF to_regclass('public.system_metrics') IS NOT NULL THEN
    v_parts := array_append(v_parts, $b$SELECT 'system_metrics', 'timestamp', 365, COUNT(*), MIN(timestamp), MAX(timestamp) FROM public.system_metrics$b$);
  END IF;
  IF to_regclass('public.alerts') IS NOT NULL THEN
    v_parts := array_append(v_parts, $b$SELECT 'alerts', 'start_time', 7, COUNT(*), MIN(start_time), MAX(start_time) FROM public.alerts$b$);
  END IF;
  IF to_regclass('public.quality_metrics') IS NOT NULL THEN
    v_parts := array_append(v_parts, $b$SELECT 'quality_metrics', 'timestamp', 7, COUNT(*), MIN(timestamp), MAX(timestamp) FROM public.quality_metrics$b$);
  END IF;
  IF to_regclass('public.deployments') IS NOT NULL THEN
    v_parts := array_append(v_parts, $b$SELECT 'deployments (adhoc)', 'created_at', 30, COUNT(*), MIN(created_at), MAX(created_at) FROM public.deployments WHERE cron_expression = '0 0 1 1 *' AND max_executions = 1 AND start_date IS NULL AND status = 'completed'$b$);
  END IF;

  IF array_length(v_parts, 1) IS NULL THEN
    RETURN;  -- nothing to summarise
  END IF;

  v_sql := 'CREATE OR REPLACE VIEW retention.policy_summary AS '
           || array_to_string(v_parts, ' UNION ALL ');
  EXECUTE v_sql;
END
$mig$;

COMMIT;
