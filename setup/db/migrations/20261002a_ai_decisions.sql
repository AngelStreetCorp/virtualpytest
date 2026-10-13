-- 20261002a_ai_decisions.sql
-- TASK-38 — Jev-style decisions: one row per call to the Decisions API (state, questions,
-- typed answers with probabilities, cost) plus the checked outcome when it is known. The
-- ground truth for decision thresholds and the fine-tuning set for a local decision model.
-- Also seeds the Jev decision profile "jev" (typesafe/jev-1.13 on the "openrouter" endpoint,
-- extra.api = "decisions", as created by hand on the lab) and the server-default route for
-- the "text.decision" usage (shared/src/lib/ai/decisions.py).
--
-- RLS: service_role only. Idempotent; the seed never overwrites edited rows.
-- Canonical twin: setup/db/schema/058_ai_decisions.sql.
-- Inverse: 20261002a_ai_decisions_rollback.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS public.ai_decisions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id     UUID NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    usage_key   TEXT NOT NULL,
    request_id  TEXT,
    profile     TEXT,
    model       TEXT,
    state       JSONB NOT NULL,
    questions   JSONB NOT NULL,
    answers     JSONB,
    ok          BOOLEAN NOT NULL,
    error       TEXT,
    ms          INTEGER NOT NULL DEFAULT 0,
    tokens_in   INTEGER NOT NULL DEFAULT 0,
    cost        NUMERIC,
    refs        JSONB NOT NULL DEFAULT '{}'::jsonb,
    outcome     JSONB,
    outcome_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ai_decisions_team_usage_idx ON public.ai_decisions (team_id, usage_key, created_at DESC);

COMMENT ON COLUMN public.ai_decisions.answers IS
    '{question_key: {type, value, probabilities, confidence}}';
COMMENT ON COLUMN public.ai_decisions.refs IS
    'What the decision was about, to match its outcome later (e.g. {alert_id})';

ALTER TABLE public.ai_decisions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_ai_decisions" ON public.ai_decisions;
CREATE POLICY "service_role_all_ai_decisions" ON public.ai_decisions
    FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.ai_decisions FROM anon, authenticated;

-- Jev on the seeded OpenRouter endpoint, and the server-default route for text.decision.
INSERT INTO public.ai_profiles (name, endpoint_id, model, extra)
SELECT 'jev', e.id, 'typesafe/jev-1.13', '{"api": "decisions"}'::jsonb
FROM public.ai_endpoints e WHERE e.name = 'openrouter'
ON CONFLICT (name) DO NOTHING;

INSERT INTO public.ai_routes (team_id, usage_key, profile_id)
SELECT NULL, 'text.decision', p.id
FROM public.ai_profiles p
WHERE p.name = 'jev'
  AND NOT EXISTS (
    SELECT 1 FROM public.ai_routes r
    WHERE r.team_id IS NULL AND r.usage_key = 'text.decision'
      AND r.host_name IS NULL AND r.device_model IS NULL AND r.userinterface_name IS NULL
);

COMMIT;
