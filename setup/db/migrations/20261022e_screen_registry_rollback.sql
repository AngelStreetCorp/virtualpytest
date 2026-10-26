-- Rollback for 20261022e: TASK-159 screen registry (the prune guard is rolled back by 20261022f_screen_prune_guard_rollback.sql).
BEGIN;

DROP FUNCTION IF EXISTS public.prune_rare_screens(uuid, text, integer, timestamptz);
DROP FUNCTION IF EXISTS public.name_screen_row(uuid, uuid, text);
DROP FUNCTION IF EXISTS public.register_screen_row(uuid, text, text, text, jsonb, text, text);
DROP TABLE IF EXISTS public.screen_unknown_counters;
DROP INDEX IF EXISTS public.idx_screen_fingerprints_merged_into;
ALTER TABLE public.screen_fingerprints DROP COLUMN IF EXISTS merged_into;

COMMIT;
