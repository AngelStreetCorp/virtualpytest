-- 064 — AI prices (TASK-87).
-- TASK-87 phase 3 — price table for cost at write time. WRITTEN, NOT YET APPLIED: apply only after the owner signs off.
--   ai_prices  USD per 1M tokens per (endpoint, model) with valid_from; model = '*' is the endpoint-wide price.
--              Used only when the provider reports no cost. No seed: prices are entered in Settings → AI → Prices
--              (a made-up price would be a wrong cost on every call).
-- Needs nothing from 20261012b_ai_calls.sql (the call log stores the computed cost itself).
-- RLS: service_role only. Idempotent. Same content as migration 20261012c_ai_prices.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS public.ai_prices (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    endpoint            TEXT NOT NULL,
    model               TEXT NOT NULL,
    price_in            NUMERIC(12, 6) NOT NULL CHECK (price_in >= 0),
    price_out           NUMERIC(12, 6) NOT NULL CHECK (price_out >= 0),
    price_cache_read    NUMERIC(12, 6) CHECK (price_cache_read IS NULL OR price_cache_read >= 0),
    price_cache_write   NUMERIC(12, 6) CHECK (price_cache_write IS NULL OR price_cache_write >= 0),
    price_web_search    NUMERIC(12, 6) CHECK (price_web_search IS NULL OR price_web_search >= 0),
    valid_from          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    note                TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ai_prices_unique UNIQUE (endpoint, model, valid_from)
);
CREATE INDEX IF NOT EXISTS ai_prices_lookup_idx ON public.ai_prices (endpoint, model, valid_from DESC);

COMMENT ON TABLE public.ai_prices IS
    'TASK-87: USD per 1M tokens (web search: per search) for an endpoint + model from valid_from on. model = * is the endpoint-wide price. Used only when the provider reports no cost; the call log stores the result at write time, so a new row never rewrites history.';

ALTER TABLE public.ai_prices ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_ai_prices" ON public.ai_prices;
CREATE POLICY "service_role_all_ai_prices" ON public.ai_prices FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.ai_prices FROM anon, authenticated;

COMMIT;
