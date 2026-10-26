-- 20261016b_screen_fingerprints_classification_attempts.sql
-- Track how many times the auto-classify scheduler has tried to name a
-- screen_fingerprints row.  After N failed attempts, the scheduler stops
-- trying — the row stays in the table for the operator to pick up by hand,
-- but the AI is no longer wasting calls on it.
--
-- WHY A COLUMN AND NOT A SEPARATE TABLE
--   The attempts counter belongs to the row it counts against.  A separate
--   table would need a join on every picker query and would lose the count
--   the moment a screen is dismissed (which currently keeps the row).
--
-- WHY DEFAULT 0, NOT NULL
--   Every existing row is a screen that has been seen at least once.  Zero
--   attempts is the right answer for the rows that pre-date this migration:
--   the scheduler will pick them up on its next run if they cross the
--   auto_classify_threshold (5) and have not been classified yet.
--
-- WHY NO RLS CHANGE
--   screen_fingerprints already has service_role-only RLS (set by
--   20261012a_screen_fingerprints.sql).  Adding a column does not change
--   the access posture.

BEGIN;

ALTER TABLE public.screen_fingerprints
    ADD COLUMN IF NOT EXISTS classification_attempts integer NOT NULL DEFAULT 0
        CHECK (classification_attempts >= 0);

-- The scheduler's hot index: pick rows that crossed the threshold and have
-- not exhausted their attempts.  Partial index on `verdict = 'unknown'`
-- so the scheduler's WHERE filter is the index scan's WHERE filter too.
CREATE INDEX IF NOT EXISTS idx_screen_fingerprints_auto_classify
    ON public.screen_fingerprints (seen_count, classification_attempts)
    WHERE verdict = 'unknown';

-- (The partial index above only contains rows the scheduler will look at
--  (verdict = 'unknown'), so the index stays small even as the table grows.
--  seen_count leads because the scheduler's first predicate is
--  `seen_count >= auto_classify_threshold`.)

COMMIT;
