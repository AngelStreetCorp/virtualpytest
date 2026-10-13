-- features/ai-dataset/db/002_triage_excluded.sql
-- TASK-27 second AI pass (2026-10-01). Adds the triage status 'excluded': a row that a
-- second blind AI answer still could not settle (it disagrees with the run label, is unsure,
-- or is a confusable pair). Its label is not changed, export_dataset.py leaves it out of
-- training, and it never goes to "Needs you" (the human is asked only when really necessary;
-- the spot-check stays). Written by features/ai-dataset/scripts/triage_batch.py import on a
-- batch exported with --second-pass. A later human answer still resolves it.
--
-- Needs 001_triage.sql. NOT applied by any deploy script: the operator applies it by hand
-- (docs/technical/FEATURES.md, "Schema is shared"). Idempotent: safe to re-run.
-- Inverse: 002_triage_excluded_rollback.sql.

BEGIN;

ALTER TABLE public.ai_training_samples
    DROP CONSTRAINT IF EXISTS ai_training_samples_triage_status_check;
ALTER TABLE public.ai_training_samples
    ADD CONSTRAINT ai_training_samples_triage_status_check
    CHECK (triage IS NULL
           OR (triage->>'status') IN ('agreed', 'needs_human', 'teacher_only', 'resolved', 'excluded'));

COMMENT ON COLUMN public.ai_training_samples.triage IS
    'TASK-27 step 4i (feature ai-dataset): AI teacher triage. status agreed (teacher = run label), needs_human (+reason), teacher_only (no independent label), resolved (a human answered), excluded (a second AI pass could not settle it: left out of training, never sent to a human). Null = never triaged.';

COMMIT;
