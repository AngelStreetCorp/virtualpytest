-- 20261012c_ai_prices_rollback.sql — inverse of 20261012c_ai_prices.sql (the entered prices are lost; stored call costs stay).

BEGIN;

DROP TABLE IF EXISTS public.ai_prices;

COMMIT;
