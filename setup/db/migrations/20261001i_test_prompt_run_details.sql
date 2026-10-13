-- 20261001i_test_prompt_run_details.sql
-- TASK-36 — what a Test Prompt run actually ran and how it ended, for the results history:
-- the prompt / acceptance criteria / target that ran (the page sends the form's values, saved or
-- not), the prompt version and whether the form differed from it, the replayed or generated
-- graph, the agent's verdict, the error, and the testcase it was saved as.
--
-- Canonical twin: setup/db/schema/033_test_prompts.sql. Idempotent.
-- Inverse: 20261001i_test_prompt_run_details_rollback.sql.

BEGIN;

ALTER TABLE public.test_prompt_executions
    ADD COLUMN IF NOT EXISTS run_details JSONB;

COMMENT ON COLUMN public.test_prompt_executions.run_details IS
    '{prompt, acceptance_criteria, target_screen_label, userinterface_name, version, edited, testcase_id?, testcase_name?, generated?, verdict?, error?, saved_testcase_id?}';

COMMIT;
