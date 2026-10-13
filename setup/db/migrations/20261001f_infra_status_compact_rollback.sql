-- 20261001f_infra_status_compact_rollback.sql
-- Inverse of 20261001f_infra_status_compact.sql: drops the live-status table and
-- restores the 90-day retention for service_status. The per-minute rows that the
-- compaction deleted are not restored. Roll back the collector code with it.

BEGIN;

DROP TABLE IF EXISTS public.service_status_current;

CREATE OR REPLACE FUNCTION retention.cleanup_infra_status()
RETURNS TABLE(deleted_count INTEGER, table_name TEXT, retention_days INTEGER)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_status INTEGER;
  v_metrics INTEGER;
BEGIN
  DELETE FROM public.service_status WHERE checked_at < NOW() - INTERVAL '90 days';
  GET DIAGNOSTICS v_status = ROW_COUNT;
  DELETE FROM public.vm_metrics WHERE timestamp < NOW() - INTERVAL '90 days';
  GET DIAGNOSTICS v_metrics = ROW_COUNT;
  RETURN QUERY SELECT v_status, 'service_status'::TEXT, 90
         UNION ALL SELECT v_metrics, 'vm_metrics'::TEXT, 90;
END;
$$;

COMMIT;

NOTIFY pgrst, 'reload schema';
