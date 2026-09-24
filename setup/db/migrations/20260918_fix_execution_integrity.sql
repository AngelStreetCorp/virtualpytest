-- Repair constraints that are present in the canonical schema but may be
-- missing from databases created before the requirements migration was applied.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class child ON child.oid = c.conrelid
        JOIN pg_class parent ON parent.oid = c.confrelid
        WHERE child.relname = 'testcase_requirements'
          AND parent.relname = 'testcase_definitions'
          AND c.contype = 'f'
          AND c.conkey = ARRAY[
              (SELECT attnum
               FROM pg_attribute
               WHERE attrelid = child.oid AND attname = 'testcase_id')
          ]
    ) THEN
        ALTER TABLE public.testcase_requirements
            ADD CONSTRAINT testcase_requirements_testcase_id_fkey
            FOREIGN KEY (testcase_id)
            REFERENCES public.testcase_definitions(testcase_id)
            ON DELETE CASCADE;
    END IF;
END $$;

-- CampaignExecutor already emits "aborted" when a user cancels a campaign.
-- Older databases had a status check that rejected that terminal state.
ALTER TABLE public.campaign_executions
    DROP CONSTRAINT IF EXISTS campaign_executions_status_check;

ALTER TABLE public.campaign_executions
    ADD CONSTRAINT campaign_executions_status_check
    CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled', 'aborted'));
