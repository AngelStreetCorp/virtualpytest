-- 20261005a_agent_turns_rollback.sql — inverse of 20261005a_agent_turns.sql.
-- Drops the agent_turns table (the chat transcript of the Agent Dashboard).

BEGIN;

DROP TABLE IF EXISTS public.agent_turns;

COMMIT;
