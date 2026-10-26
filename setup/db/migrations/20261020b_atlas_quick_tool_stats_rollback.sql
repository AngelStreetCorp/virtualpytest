-- 20261020b_atlas_quick_tool_stats_rollback.sql — inverse of 20261020b_atlas_quick_tool_stats.sql.

BEGIN;

DROP FUNCTION IF EXISTS public.atlas_quick_tool_bump(UUID, TEXT, TEXT, INTEGER, INTEGER, INTEGER);
DROP TABLE IF EXISTS public.atlas_quick_tool_stats;

COMMIT;
