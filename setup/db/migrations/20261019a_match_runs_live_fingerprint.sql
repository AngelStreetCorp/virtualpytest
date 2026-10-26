-- 20261019a_match_runs_live_fingerprint.sql
-- Store the live frame's fingerprint (regions) on a match run, so the operator can mark a
-- run "Wrong screen?" afterwards (TASK-137 goal 7) and /localize/verdict gets the same
-- payload the Localize button sends.  NULL for runs older than this migration and for paths
-- whose matcher computes no fingerprint (the per-frame monitor).

BEGIN;

ALTER TABLE public.match_runs
    ADD COLUMN IF NOT EXISTS live_fingerprint jsonb;

COMMENT ON COLUMN public.match_runs.live_fingerprint IS
    'Live frame fingerprint {v, dhash, regions, crop, focus} the matcher compared with the node fingerprints.  '
    'NULL when none was computed.  Source: NavigationExecutor.localize().';

COMMIT;
