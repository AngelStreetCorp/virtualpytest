-- 20261001h_test_prompt_tool_trace_rollback.sql
-- Inverse of 20261001h_test_prompt_tool_trace.sql. Apply BEFORE deploying the older code: it
-- never reads tool_trace, but drop it so the schema matches 033_test_prompts.sql of that build.

BEGIN;

ALTER TABLE public.test_prompt_executions DROP COLUMN IF EXISTS tool_trace;

COMMIT;
