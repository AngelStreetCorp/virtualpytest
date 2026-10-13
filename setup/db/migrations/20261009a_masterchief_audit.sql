-- TASK-71: masterchief audit table (Parts 7.1).
-- One row per masterchief op attempt. Written by vpt-server (service role) at three checkpoints:
--   1. propose  (state='proposed')  — in-process MCP tool, no human yet
--   2. execute  (state='executing') — browser confirmation, before the op runs
--   3. terminal (state='executed' | 'failed' | 'refused') — after the op or after a gate refusal
-- Same RLS lockdown as agent_turns (20260908b_close_app_tables_to_public_key) and agent_turns
-- itself (20261005a). Idempotent. The only table masterchief may write.

BEGIN;

CREATE TABLE IF NOT EXISTS public.masterchief_audit (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id             UUID NOT NULL,
    requester_user_id   TEXT NOT NULL,
    requester_email     TEXT,
    requester_role      TEXT NOT NULL,
    op                  TEXT NOT NULL,
    params_redacted     JSONB NOT NULL DEFAULT '{}'::jsonb,
    host                TEXT,
    state               TEXT NOT NULL CHECK (state IN ('proposed','executing','executed','failed','refused')),
    result_summary      TEXT,
    duration_ms         INTEGER,
    trace_id            TEXT,
    session_id          TEXT,
    at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_masterchief_audit_team_at
    ON public.masterchief_audit (team_id, at DESC);
CREATE INDEX IF NOT EXISTS idx_masterchief_audit_state
    ON public.masterchief_audit (state) WHERE state IN ('executing','proposed');
CREATE INDEX IF NOT EXISTS idx_masterchief_audit_op
    ON public.masterchief_audit (op, at DESC);
CREATE INDEX IF NOT EXISTS idx_masterchief_audit_requester
    ON public.masterchief_audit (requester_user_id, at DESC);

COMMENT ON TABLE public.masterchief_audit IS
    'TASK-71 masterchief ops audit. Written by vpt-server only. RLS service_role only. '
    'The only table masterchief may write to. Reads filtered by team_id; scope=platform is the '
    'documented exception (CONTRACTS #29 pending ratification).';
COMMENT ON COLUMN public.masterchief_audit.params_redacted IS
    'Op params after redaction: no file contents, no journal bodies, no env values, no command output. '
    'Strings are trimmed to a small cap; sensitive-looking keys are dropped.';
COMMENT ON COLUMN public.masterchief_audit.result_summary IS
    'Capped digest of the op result. Same redaction as params_redacted.';

ALTER TABLE public.masterchief_audit ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_masterchief_audit" ON public.masterchief_audit;
CREATE POLICY "service_role_all_masterchief_audit" ON public.masterchief_audit
    FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.masterchief_audit FROM anon, authenticated;

COMMIT;
