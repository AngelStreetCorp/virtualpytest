-- Rollback of 20261018b_screen_fingerprints_fingerprint.sql

BEGIN;

ALTER TABLE public.screen_fingerprints
    DROP COLUMN IF EXISTS fingerprint;

COMMIT;
