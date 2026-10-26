-- Rollback of 20261014e_localize_verdicts.sql. Corrections already written into
-- navigation_nodes.data.fingerprint (extra / negatives) stay; undo them first if needed.
BEGIN;
DROP TABLE IF EXISTS public.localize_verdicts;
ALTER TABLE public.screen_fingerprints DROP COLUMN IF EXISTS label;
COMMIT;
