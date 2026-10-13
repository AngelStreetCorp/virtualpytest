-- 20260930b_training_family_content_type_rollback.sql
-- Inverse of 20260930b_training_family_content_type.sql: deletes the 'content-type' samples
-- (their frames stay in the bucket), then restores the previous family CHECK.

BEGIN;

DELETE FROM public.ai_training_samples WHERE family = 'content-type';

ALTER TABLE public.ai_training_samples DROP CONSTRAINT IF EXISTS ai_training_samples_family_check;
ALTER TABLE public.ai_training_samples ADD CONSTRAINT ai_training_samples_family_check
    CHECK (family IN ('screen-id', 'focus', 'menu', 'banner', 'av-fault', 'other'));

COMMIT;
