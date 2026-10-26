-- 20261018f_ai_budgets_drop_team_id_rollback.sql — inverse of 20261018f_ai_budgets_drop_team_id.sql.
-- Restores team_id (filled from team_scope) so the 20261016d rollback can re-key on it.

BEGIN;

ALTER TABLE public.ai_budgets
    ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES public.teams(id) ON DELETE CASCADE;
UPDATE public.ai_budgets SET team_id = team_scope WHERE team_id IS NULL;
ALTER TABLE public.ai_budgets ALTER COLUMN team_id SET NOT NULL;
ALTER TABLE public.ai_budgets ALTER COLUMN team_scope DROP NOT NULL;

COMMIT;
