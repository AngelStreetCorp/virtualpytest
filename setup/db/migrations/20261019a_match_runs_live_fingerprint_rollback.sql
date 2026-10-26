-- 20261019a_match_runs_live_fingerprint_rollback.sql — inverse of 20261019a_match_runs_live_fingerprint.sql.

BEGIN;

ALTER TABLE public.match_runs DROP COLUMN IF EXISTS live_fingerprint;

COMMIT;
