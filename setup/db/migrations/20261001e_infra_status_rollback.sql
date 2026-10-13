-- 20261001e_infra_status_rollback.sql
-- Inverse of 20261001e_infra_status.sql: drops the infra-status history.

BEGIN;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
    PERFORM cron.unschedule(jobid) FROM cron.job WHERE jobname = 'cleanup-infra-status';
  END IF;
END $$;

DROP FUNCTION IF EXISTS retention.cleanup_infra_status();
DROP TABLE IF EXISTS public.vm_metrics;
DROP TABLE IF EXISTS public.service_status;

COMMIT;

NOTIFY pgrst, 'reload schema';
