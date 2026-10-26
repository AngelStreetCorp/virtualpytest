-- 20261013b_alerts_profile_rollback.sql — inverse of 20261013b_alerts_profile.sql.
-- The CHECK comes back as NOT VALID: rows of other profiles that already exist stay (nothing is deleted), only new
-- inserts are held to the six TV types (the five of before plus no_signal, a first-class incident type since BUG-0504; main's own
-- CHECK still lists five, so a no_signal alert cannot be inserted on a database that only has main's schema). Delete or fix those rows, then `ALTER TABLE alerts VALIDATE CONSTRAINT
-- alerts_incident_type_check;` to make it a full constraint again.

BEGIN;

DROP INDEX IF EXISTS public.idx_alerts_profile;

ALTER TABLE public.alerts DROP COLUMN IF EXISTS profile;

ALTER TABLE public.alerts DROP CONSTRAINT IF EXISTS alerts_incident_type_check;
ALTER TABLE public.alerts ADD CONSTRAINT alerts_incident_type_check
    CHECK (incident_type = ANY (ARRAY['blackscreen'::text, 'no_signal'::text, 'freeze'::text, 'errors'::text, 'audio_loss'::text, 'macroblocks'::text])) NOT VALID;

COMMIT;
