-- 20261001g_service_status_stopped.sql
-- service_status / service_status_current gain the status 'stopped': a service that is
-- not running because it was switched off, told apart from 'down' (failing: crashed,
-- stuck, missing). Before this, a stopped optional service read as 'unknown'.
-- Existing rows recorded as 'unknown' with detail 'stopped' are relabelled.
--
-- Canonical twin: setup/db/schema/057_infra_status.sql. Idempotent.
-- Inverse: 20261001g_service_status_stopped_rollback.sql.

BEGIN;

ALTER TABLE public.service_status DROP CONSTRAINT IF EXISTS service_status_status_check;
ALTER TABLE public.service_status ADD CONSTRAINT service_status_status_check
    CHECK (status IN ('ok', 'stopped', 'degraded', 'down', 'unknown'));

ALTER TABLE public.service_status_current DROP CONSTRAINT IF EXISTS service_status_current_status_check;
ALTER TABLE public.service_status_current ADD CONSTRAINT service_status_current_status_check
    CHECK (status IN ('ok', 'stopped', 'degraded', 'down', 'unknown'));

UPDATE public.service_status SET status = 'stopped' WHERE status = 'unknown' AND detail = 'stopped';
UPDATE public.service_status_current SET status = 'stopped' WHERE status = 'unknown' AND detail = 'stopped';

COMMIT;

NOTIFY pgrst, 'reload schema';
