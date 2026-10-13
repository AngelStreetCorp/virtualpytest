-- 061 — Agent turns (TASK-54).
-- TASK-54 Q3: chat transcript of the AI agents (Atlas, Sherlock, Nightwatch) for the Agent Dashboard.
-- One row per message of a chat turn (user + agent), the agent row carries the tool calls, the tokens
-- of the turn and the Langfuse trace id. Written by vpt-server (service role), pruned after 30 days by
-- the server itself. RLS on, service_role only (same lockdown as 20260908b_close_app_tables_to_public_key).
-- Idempotent. Same content as migration 20261005a_agent_turns.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS public.agent_turns (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id     UUID NOT NULL,
    agent_id    TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    task_id     TEXT,
    turn_index  INTEGER NOT NULL DEFAULT 0,
    role        TEXT NOT NULL CHECK (role IN ('user', 'agent', 'tool')),
    content     TEXT,
    tool_calls  JSONB,
    tokens_in   INTEGER,
    tokens_out  INTEGER,
    trace_id    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_turns_team_agent_created
    ON public.agent_turns (team_id, agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_turns_session
    ON public.agent_turns (session_id);
CREATE INDEX IF NOT EXISTS idx_agent_turns_task
    ON public.agent_turns (task_id) WHERE task_id IS NOT NULL;

COMMENT ON TABLE public.agent_turns IS
    'TASK-54 chat transcript per message (user/agent). agent_id is the registry id (assistant, analyzer, '
    'monitor). Pruned after 30 days by the server. Every read filters by team_id.';
COMMENT ON COLUMN public.agent_turns.trace_id IS
    'Langfuse trace id of the last generation of the turn; the link is built from LANGFUSE_HOST.';

ALTER TABLE public.agent_turns ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_agent_turns" ON public.agent_turns;
CREATE POLICY "service_role_all_agent_turns" ON public.agent_turns
    FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.agent_turns FROM anon, authenticated;

COMMIT;
