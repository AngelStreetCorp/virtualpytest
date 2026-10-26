-- Rollback for 20261018c: screen_fingerprints.userinterface.

BEGIN;

ALTER TABLE public.screen_fingerprints
    DROP COLUMN IF EXISTS userinterface;

COMMIT;
