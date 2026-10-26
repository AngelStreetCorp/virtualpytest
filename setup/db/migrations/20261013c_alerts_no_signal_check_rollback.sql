-- 20261013c_alerts_no_signal_check_rollback.sql — inverse of 20261013c_alerts_no_signal_check.sql.
-- The CHECK goes back to the five older types as NOT VALID: no_signal rows that already exist stay (nothing is deleted), only new inserts are held
-- to the five. Delete or fix those rows, then `ALTER TABLE alerts VALIDATE CONSTRAINT alerts_incident_type_check;` to make it a full constraint.
-- A no-op when the constraint does not exist.

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'alerts_incident_type_check' AND conrelid = 'public.alerts'::regclass) THEN
        ALTER TABLE public.alerts DROP CONSTRAINT alerts_incident_type_check;
        ALTER TABLE public.alerts ADD CONSTRAINT alerts_incident_type_check
            CHECK (incident_type = ANY (ARRAY['blackscreen'::text, 'freeze'::text, 'errors'::text, 'audio_loss'::text, 'macroblocks'::text])) NOT VALID;
    END IF;
END
$$;

COMMIT;
