-- features/ai-dataset/db/002_triage_excluded_rollback.sql
-- Inverse of 002_triage_excluded.sql: the CHECK back to the 001 vocabulary. Refused while a
-- row still has status 'excluded'; first move those rows back to the human, e.g.
--   UPDATE public.ai_training_samples
--      SET triage = jsonb_set(triage, '{status}', '"needs_human"')
--    WHERE triage->>'status' = 'excluded';

BEGIN;

ALTER TABLE public.ai_training_samples
    DROP CONSTRAINT IF EXISTS ai_training_samples_triage_status_check;
ALTER TABLE public.ai_training_samples
    ADD CONSTRAINT ai_training_samples_triage_status_check
    CHECK (triage IS NULL
           OR (triage->>'status') IN ('agreed', 'needs_human', 'teacher_only', 'resolved'));

COMMENT ON COLUMN public.ai_training_samples.triage IS
    'TASK-27 step 4i (feature ai-dataset): AI teacher triage. status agreed (teacher = run label), needs_human (+reason), teacher_only (no independent label), resolved (a human answered). Null = never triaged.';

COMMIT;
