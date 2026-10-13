-- 20261001b_test_prompt_run_mode_rollback.sql
-- Inverse of 20261001b_test_prompt_run_mode.sql. Apply BEFORE deploying the older code: it
-- never reads run_mode, but drop it so the schema matches 033_test_prompts.sql of that build.

BEGIN;

ALTER TABLE public.test_prompt_executions DROP CONSTRAINT IF EXISTS test_prompt_executions_run_mode_check;
ALTER TABLE public.test_prompt_executions DROP COLUMN IF EXISTS run_mode;

COMMIT;
