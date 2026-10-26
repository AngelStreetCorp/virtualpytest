-- 071 — BUG-0612: drop the legacy ai_budgets.team_id.
--
-- 20261016d (finer buckets) re-keyed ai_budgets on (bucket_type, bucket_id) and moved the owning team to
-- team_scope, but left the old team_id column NOT NULL. upsert_bucket never sets it, so every budget other
-- than a team budget (endpoint, model, user, usage, project) failed with a not-null violation. Nothing
-- reads team_id any more: drop it, and make team_scope NOT NULL as its column comment already says.
--
-- Idempotent. Same content as migration 20261018f_ai_budgets_drop_team_id.sql.

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'ai_budgets' AND column_name = 'team_id') THEN
        UPDATE public.ai_budgets SET team_scope = team_id WHERE team_scope IS NULL;
    END IF;
END $$;

ALTER TABLE public.ai_budgets ALTER COLUMN team_scope SET NOT NULL;
ALTER TABLE public.ai_budgets DROP COLUMN IF EXISTS team_id;

COMMIT;
