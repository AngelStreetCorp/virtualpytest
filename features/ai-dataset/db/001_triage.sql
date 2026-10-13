-- features/ai-dataset/db/001_triage.sql
-- TASK-27 step 4i. AI triage metadata on ai_training_samples, owned by the ai-dataset
-- feature (only the feature reads or writes it; core reads use select('*') and never
-- depend on it). NOT applied by any deploy script: the operator applies it by hand
-- (docs/technical/FEATURES.md, "Schema is shared").
--
--   * ai_training_samples.triage  one JSON object per row, null until a teacher
--     (AI) looked at the row. Written by features/ai-dataset/scripts/triage_batch.py
--     import and by the review label route (status -> resolved):
--       {"status": "agreed" | "needs_human" | "teacher_only" | "resolved",
--        "reason": null | "disagrees_with_run" | "conflict" | "low_confidence"
--                  | "spot_check" | "no_independent_label",
--        "teacher_model": "claude-sonnet-5", "teacher_answer": {...},
--        "teacher_label": {...}, "teacher_confidence": "high" | "low",
--        "teacher_note": "...", "batch_id": "...", "triaged_at": "...",
--        "prior_status": ..., "resolved_at": ..., "human_agreed_with_teacher": ...}
--   * a CHECK on triage->>'status' (the vocabulary above)
--   * an index on (team_id, triage->>'status') for the "Needs you" view and the
--     eval-v0-ai freeze count
--
-- The frozen-row trigger of 20260927a guards ground_truth and split only, so a
-- triage change on a frozen row is allowed (the tooling never makes one).
--
-- Idempotent: safe to re-run. Inverse: 001_triage_rollback.sql.

BEGIN;

ALTER TABLE public.ai_training_samples
    ADD COLUMN IF NOT EXISTS triage JSONB;

ALTER TABLE public.ai_training_samples
    DROP CONSTRAINT IF EXISTS ai_training_samples_triage_status_check;
ALTER TABLE public.ai_training_samples
    ADD CONSTRAINT ai_training_samples_triage_status_check
    CHECK (triage IS NULL
           OR (triage->>'status') IN ('agreed', 'needs_human', 'teacher_only', 'resolved'));

CREATE INDEX IF NOT EXISTS idx_ai_training_samples_triage_status
    ON public.ai_training_samples(team_id, (triage->>'status'))
    WHERE triage IS NOT NULL;

COMMENT ON COLUMN public.ai_training_samples.triage IS
    'TASK-27 step 4i (feature ai-dataset): AI teacher triage. status agreed (teacher = run label), needs_human (+reason), teacher_only (no independent label), resolved (a human answered). Null = never triaged.';

COMMIT;
