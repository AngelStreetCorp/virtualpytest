-- 20261001h_test_prompt_tool_trace.sql
-- TASK-36 phase 2 — keep a passing exploration's device steps so it can be saved as a testcase:
-- the pre-navigation and each successful navigate_to_node / execute_device_action call, in order.
--
-- Canonical twin: setup/db/schema/033_test_prompts.sql. Idempotent.
-- Inverse: 20261001h_test_prompt_tool_trace_rollback.sql.

BEGIN;

ALTER TABLE public.test_prompt_executions
    ADD COLUMN IF NOT EXISTS tool_trace JSONB;

COMMENT ON COLUMN public.test_prompt_executions.tool_trace IS
    'Exploration only: [{tool: navigate_to_node|execute_device_action, params}] of the successful device steps, in order';

COMMIT;
