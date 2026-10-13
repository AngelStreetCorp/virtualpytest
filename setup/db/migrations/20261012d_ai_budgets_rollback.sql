-- 20261012d_ai_budgets_rollback.sql — inverse of 20261012d_ai_budgets.sql (the budgets are lost).

BEGIN;

DROP TABLE IF EXISTS public.ai_budgets;

COMMIT;
