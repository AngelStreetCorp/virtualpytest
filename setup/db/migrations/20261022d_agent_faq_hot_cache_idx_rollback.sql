-- Rollback of 20261022d_agent_faq_hot_cache_idx.sql. Drops only the hot-cache index; no data change.
BEGIN;
DROP INDEX IF EXISTS public.agent_faq_hot_cache_idx;
COMMIT;
