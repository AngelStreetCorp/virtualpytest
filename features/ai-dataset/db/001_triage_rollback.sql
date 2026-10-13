-- features/ai-dataset/db/001_triage_rollback.sql
-- Inverse of 001_triage.sql. Drops the index, the CHECK and the triage column.
-- Destroys every triage record (teacher model, answer, confidence, reason); the
-- labels themselves (ground_truth, label_source) are not touched. Rows an AI
-- teacher labelled keep label_source='teacher'.

BEGIN;

DROP INDEX IF EXISTS public.idx_ai_training_samples_triage_status;

ALTER TABLE public.ai_training_samples
    DROP CONSTRAINT IF EXISTS ai_training_samples_triage_status_check;

ALTER TABLE public.ai_training_samples
    DROP COLUMN IF EXISTS triage;

COMMIT;
