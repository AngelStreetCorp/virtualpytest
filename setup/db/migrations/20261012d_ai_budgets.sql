-- 20261012d_ai_budgets.sql
-- TASK-87 phase 4 — monthly AI budget per team. WRITTEN, NOT YET APPLIED: apply only after the owner signs off.
--   ai_budgets  one row per team: month limit (USD), mode warn | block, warn threshold. No row = no budget.
-- Spend comes from ai_usage_stats.cost (priced calls only, see 20261012b / 20261012c). A missing table or row
-- never blocks a call (the lookup fails open).
-- RLS: service_role only. Idempotent. Canonical twin: setup/db/schema/065_ai_budgets.sql. Inverse: 20261012d_ai_budgets_rollback.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS public.ai_budgets (
    team_id          UUID PRIMARY KEY REFERENCES public.teams(id) ON DELETE CASCADE,
    month_limit_usd  NUMERIC(12, 2) NOT NULL CHECK (month_limit_usd > 0),
    mode             TEXT NOT NULL DEFAULT 'warn' CHECK (mode IN ('warn', 'block')),
    warn_at          NUMERIC(3, 2) NOT NULL DEFAULT 0.80 CHECK (warn_at > 0 AND warn_at <= 1),
    updated_by       TEXT,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.ai_budgets IS
    'TASK-87 phase 4: monthly AI budget per team (USD, priced calls only). mode = warn shows it on Monitoring -> AI usage; mode = block also refuses the team''s AI calls once the month''s spend reaches the limit (gateway.execute, agent turns).';

ALTER TABLE public.ai_budgets ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_ai_budgets" ON public.ai_budgets;
CREATE POLICY "service_role_all_ai_budgets" ON public.ai_budgets FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.ai_budgets FROM anon, authenticated;

COMMIT;
