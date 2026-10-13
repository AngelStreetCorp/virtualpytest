-- 20260930b_training_family_content_type.sql
-- TASK-05 — new training-sample family 'content-type': the live-TV companion's identify call
-- (screen type, content category, programme) recorded for fine-tuning (TASK-27).
--
-- Canonical twin: setup/db/migrations/20260927a_ai_training_samples.sql (no schema/ file).
-- Idempotent. Inverse: 20260930b_training_family_content_type_rollback.sql.

BEGIN;

ALTER TABLE public.ai_training_samples DROP CONSTRAINT IF EXISTS ai_training_samples_family_check;
ALTER TABLE public.ai_training_samples ADD CONSTRAINT ai_training_samples_family_check
    CHECK (family IN ('screen-id', 'focus', 'menu', 'banner', 'av-fault', 'content-type', 'other'));

COMMIT;
