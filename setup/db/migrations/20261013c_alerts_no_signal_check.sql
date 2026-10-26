-- 20261013c_alerts_no_signal_check.sql — BUG-0504: allow 'no_signal' alerts. Adds ONLY no_signal to the CHECK on alerts.incident_type.
-- Main's CHECK lists blackscreen, freeze, errors, audio_loss, macroblocks; the monitor now raises no_signal as a first-class incident type, and the
-- insert of such an alert is refused until the type is allowed. For a database that gets tv_app alone and not the profile column of
-- 20261013b_alerts_profile (which drops this CHECK altogether).
-- Idempotent, and a no-op when the constraint does not exist (after 20261013b, or on a fresh database built from schema/005, which has none).
-- Inverse: 20261013c_alerts_no_signal_check_rollback.sql. Not applied anywhere yet (owner decision).

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'alerts_incident_type_check' AND conrelid = 'public.alerts'::regclass) THEN
        ALTER TABLE public.alerts DROP CONSTRAINT alerts_incident_type_check;
        ALTER TABLE public.alerts ADD CONSTRAINT alerts_incident_type_check
            CHECK (incident_type = ANY (ARRAY['blackscreen'::text, 'no_signal'::text, 'freeze'::text, 'errors'::text, 'audio_loss'::text, 'macroblocks'::text]));
    END IF;
END
$$;

COMMIT;
