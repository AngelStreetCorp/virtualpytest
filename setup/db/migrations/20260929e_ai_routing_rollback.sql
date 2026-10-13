-- 20260929e_ai_routing_rollback.sql
-- Inverse of 20260929e_ai_routing.sql (TASK-30). Drops the AI routing tables.
-- ⚠ Only after redeploying code that predates TASK-30 (it reads AI_* env vars again).

BEGIN;

DROP FUNCTION IF EXISTS public.ai_usage_stats_bump(TEXT, UUID, TEXT, TEXT, TEXT, BOOLEAN, BOOLEAN, INTEGER, INTEGER, INTEGER);
DROP TABLE IF EXISTS public.ai_usage_stats;
DROP TRIGGER IF EXISTS ai_routes_protect_roots ON public.ai_routes;
DROP TABLE IF EXISTS public.ai_routes;
DROP FUNCTION IF EXISTS public.ai_routes_protect_roots();
DROP TABLE IF EXISTS public.ai_profiles;
DROP TABLE IF EXISTS public.ai_endpoints;

COMMIT;
