-- 20261020g — AI benchmarks (TASK-143).
-- TASK-143 — one row per benchmark CASE: a fixed test case of a usage key, run against a named
-- model profile. The case set is the frozen input (docs/agent/ai/benchmarks/cases/<usage key>.jsonl),
-- the runner is scripts/ai_bench.py, and the per-run summary is appended to
-- docs/agent/ai/benchmarks/bench-<usage key>.jsonl (the same JSONL shape benchmark_log.py reads).
-- This table is the machine-readable half: what Grafana and the AI usage page read.
--
-- One row per (run, case). A run = one (usage key, model profile, case set) triple; run_id groups
-- its rows. request_id is the Langfuse trace id of the call, so a case links to its call-log row
-- and to its trace.
--
-- The table was applied to the lab database before the storage of the results moved to the AI
-- call log: a benchmark case IS an AI call, so the results live in ai_calls (the label
-- eval:<usage key>, the verdict of the case in parse_ok, the run and case ids in ref_type /
-- ref_id / ref_kind) and Grafana and Monitoring -> AI usage read those rows. The table stays
-- empty; it is here so that the applied schema of the database matches the repository.
--
-- RLS: service_role only. Idempotent.
-- Same content as setup/db/schema/077_ai_benchmarks.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS public.ai_benchmarks (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_id       UUID NOT NULL,
    team_id      UUID,
    uc           TEXT NOT NULL,                 -- bench-<usage key>
    usage_key    TEXT NOT NULL,                 -- the production usage key the cases exercise
    profile      TEXT NOT NULL,                 -- the named model profile the run pinned
    model        TEXT,
    endpoint     TEXT,
    case_id      TEXT NOT NULL,                 -- the case inside the case set
    kind         TEXT,                          -- text | vision | decision
    ok           BOOLEAN NOT NULL,              -- the case's check passed
    score        NUMERIC(4, 3),                 -- 0..1, the case score
    error        TEXT,
    ms           INTEGER NOT NULL DEFAULT 0,
    tokens_in    INTEGER NOT NULL DEFAULT 0,
    tokens_out   INTEGER NOT NULL DEFAULT 0,
    cost         NUMERIC(14, 8),
    request_id   TEXT,                          -- Langfuse trace id = ai_calls.request_id
    prompt_sha   TEXT,                          -- sha of the frozen prompt, so a changed case is visible
    checks       JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ai_benchmarks_ts_idx ON public.ai_benchmarks (ts);
CREATE INDEX IF NOT EXISTS ai_benchmarks_key_ts_idx ON public.ai_benchmarks (usage_key, ts DESC);
CREATE INDEX IF NOT EXISTS ai_benchmarks_run_idx ON public.ai_benchmarks (run_id);
CREATE INDEX IF NOT EXISTS ai_benchmarks_team_ts_idx ON public.ai_benchmarks (team_id, ts DESC);

COMMENT ON TABLE public.ai_benchmarks IS
    'One row per benchmark case (TASK-143): a fixed case of a usage key run against a named model profile.';
COMMENT ON COLUMN public.ai_benchmarks.checks IS
    'What the check looked for and what came back, per named check ({contains: {expected, found}})';
COMMENT ON COLUMN public.ai_benchmarks.score IS
    '0..1: the share of the case checks that passed';

ALTER TABLE public.ai_benchmarks ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_ai_benchmarks" ON public.ai_benchmarks;
CREATE POLICY "service_role_all_ai_benchmarks" ON public.ai_benchmarks
    FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.ai_benchmarks FROM anon, authenticated;

COMMIT;
