-- 20261016d_ai_budgets_finer_buckets_rollback.sql
-- Inverse of 20261016d_ai_budgets_finer_buckets.sql. All finer buckets are dropped (their spend is not recoverable),
-- and the only preserved rows are team-bucket rows (one per team that had a budget at apply time).

BEGIN;

-- 1. ai_calls
DROP INDEX IF EXISTS public.ai_calls_project_ts_idx;
DROP INDEX IF EXISTS public.ai_calls_team_user_ts_idx;
ALTER TABLE public.ai_calls DROP COLUMN IF EXISTS project_id;

-- 2. ai_budgets — keep only team rows, drop the rest, restore PK on team_id
DELETE FROM public.ai_budgets WHERE bucket_type <> 'team';

ALTER TABLE public.ai_budgets DROP CONSTRAINT IF EXISTS ai_budgets_pkey;
ALTER TABLE public.ai_budgets ADD PRIMARY KEY (team_id);

DROP INDEX IF EXISTS public.ai_budgets_team_scope_idx;

ALTER TABLE public.ai_budgets DROP COLUMN IF EXISTS team_scope;
ALTER TABLE public.ai_budgets DROP COLUMN IF EXISTS label;
ALTER TABLE public.ai_budgets DROP COLUMN IF EXISTS bucket_id;
ALTER TABLE public.ai_budgets DROP COLUMN IF EXISTS bucket_type;

COMMIT;