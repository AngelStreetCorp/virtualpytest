-- 20261023a_screen_label_worker.sql
-- TASK-162: the screen-label worker's own bookkeeping on screen_fingerprints. ADDITIVE only
-- (rollback: 20261023a_screen_label_worker_rollback.sql). No existing column is changed or dropped.
--
-- WHY NEW COLUMNS AND NOT classification_attempts
--   classification_attempts is the budget of auto_classify_unknowns.py's classifier. It is
--   monotonically shared with a picker this task does not control, and it has already reached 3
--   (MAX_ATTEMPTS) on 9 of the 18 named in-scope rows, which would make them invisible to any
--   later worker. The label worker needs its own budget and its own verdict columns so the two
--   processes cannot starve each other.
--
-- WHAT EACH COLUMN IS FOR
--   label_state      one word for why the row is in the state it is in, so the daily report and the
--                    human review list are a SELECT rather than a re-inference:
--                      live     the image answered LIVE to the first closed question. Not a screen the
--                               owner asked to name; never given a label.
--                      named    this worker wrote a label through name_screen_row (single writer).
--                      review   the model was not confident enough; left as unknown_N for a person.
--                      proposed a name is proposed in userinterface_unknown_screens (the operator's
--                               existing "Needs a name" queue) but no tree node exists for it yet.
--                      disagree a verification pass with a different prompt did not confirm the name.
--   label_note       the model's own words: the raw answer, the reason for review, or the disagreement.
--   label_profile    the AI profile that decided it, so a later run can tell a free-model label from
--                    a paid one when the agreement rate has to be explained.
--   label_attempts   the label worker's own budget (MAX_LABEL_ATTEMPTS). Independent of the other one.
--   linked_node_id   the navigation node this screen matched by fingerprint, when one did. The
--                    interface is NOT stored: it comes from the node that matched, never guessed
--                    (TASK-159 G6).
--   labeled_at       when the worker last decided something about this row.
--
-- The label itself is NEVER stored here: names go through name_screen_row(), which only writes a row
-- whose label is NULL or unknown_N (TASK-159 G4). This migration adds no way to write a label.
BEGIN;

ALTER TABLE public.screen_fingerprints ADD COLUMN IF NOT EXISTS label_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE public.screen_fingerprints ADD COLUMN IF NOT EXISTS label_state TEXT;
ALTER TABLE public.screen_fingerprints ADD COLUMN IF NOT EXISTS label_note TEXT;
ALTER TABLE public.screen_fingerprints ADD COLUMN IF NOT EXISTS label_profile TEXT;
ALTER TABLE public.screen_fingerprints ADD COLUMN IF NOT EXISTS linked_node_id TEXT;
ALTER TABLE public.screen_fingerprints ADD COLUMN IF NOT EXISTS labeled_at TIMESTAMPTZ;

-- The picker: unnamed rows of a team, still within their own budget, most-seen first.
CREATE INDEX IF NOT EXISTS idx_screen_fingerprints_label_picker
    ON public.screen_fingerprints (team_id, seen_count DESC)
    WHERE merged_into IS NULL
      AND label_attempts < 6
      AND (label IS NULL OR label ~ '^unknown_[0-9]+$');

-- The human review list and the disagreement list.
CREATE INDEX IF NOT EXISTS idx_screen_fingerprints_label_state
    ON public.screen_fingerprints (team_id, label_state, seen_count DESC)
    WHERE merged_into IS NULL AND label_state IS NOT NULL;

COMMIT;