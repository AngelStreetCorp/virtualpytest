-- 20261001g_service_status_stopped_rollback.sql
-- Inverse of 20261001g_service_status_stopped.sql: 'stopped' rows go back to 'unknown'
-- and the status check loses 'stopped'. Roll back the collector code with it.

BEGIN;

UPDATE public.service_status SET status = 'unknown' WHERE status = 'stopped';
UPDATE public.service_status_current SET status = 'unknown' WHERE status = 'stopped';

ALTER TABLE public.service_status DROP CONSTRAINT IF EXISTS service_status_status_check;
ALTER TABLE public.service_status ADD CONSTRAINT service_status_status_check
    CHECK (status IN ('ok', 'degraded', 'down', 'unknown'));

ALTER TABLE public.service_status_current DROP CONSTRAINT IF EXISTS service_status_current_status_check;
ALTER TABLE public.service_status_current ADD CONSTRAINT service_status_current_status_check
    CHECK (status IN ('ok', 'degraded', 'down', 'unknown'));

COMMIT;

NOTIFY pgrst, 'reload schema';
