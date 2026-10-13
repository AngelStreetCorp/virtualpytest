-- 20261001i_test_prompt_run_details_rollback.sql
-- Inverse of 20261001i_test_prompt_run_details.sql. Apply BEFORE deploying the older code: it
-- never reads run_details, but drop it so the schema matches 033_test_prompts.sql of that build.

BEGIN;

ALTER TABLE public.test_prompt_executions DROP COLUMN IF EXISTS run_details;

COMMIT;
