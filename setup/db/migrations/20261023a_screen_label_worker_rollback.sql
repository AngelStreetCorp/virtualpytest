-- Rollback for 20261023a: removes the TASK-162 screen-label worker's bookkeeping columns and its two
-- indexes. The labels the worker already wrote stay (they live in the `label` column, written through
-- name_screen_row): this rollback does not un-name a screen.
BEGIN;

DROP INDEX IF EXISTS public.idx_screen_fingerprints_label_picker;
DROP INDEX IF EXISTS public.idx_screen_fingerprints_label_state;

ALTER TABLE public.screen_fingerprints DROP COLUMN IF EXISTS labeled_at;
ALTER TABLE public.screen_fingerprints DROP COLUMN IF EXISTS linked_node_id;
ALTER TABLE public.screen_fingerprints DROP COLUMN IF EXISTS label_profile;
ALTER TABLE public.screen_fingerprints DROP COLUMN IF EXISTS label_note;
ALTER TABLE public.screen_fingerprints DROP COLUMN IF EXISTS label_state;
ALTER TABLE public.screen_fingerprints DROP COLUMN IF EXISTS label_attempts;

COMMIT;