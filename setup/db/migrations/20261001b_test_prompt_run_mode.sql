-- 20261001b_test_prompt_run_mode.sql
-- TASK-36 — a Test Prompt run is either an agent exploration or a testcase-graph run; record
-- which engine ran it. Existing rows were all explorations.
--
-- Canonical twin: setup/db/schema/033_test_prompts.sql. Idempotent.
-- Inverse: 20261001b_test_prompt_run_mode_rollback.sql.

BEGIN;

ALTER TABLE public.test_prompt_executions
    ADD COLUMN IF NOT EXISTS run_mode VARCHAR(10) NOT NULL DEFAULT 'explore';
ALTER TABLE public.test_prompt_executions DROP CONSTRAINT IF EXISTS test_prompt_executions_run_mode_check;
ALTER TABLE public.test_prompt_executions ADD CONSTRAINT test_prompt_executions_run_mode_check
    CHECK (run_mode IN ('explore', 'graph'));

COMMENT ON COLUMN public.test_prompt_executions.run_mode IS
    'explore = Atlas agent drove the device; graph = the prompt''s testcase graph ran on the testcase executor';

COMMIT;
