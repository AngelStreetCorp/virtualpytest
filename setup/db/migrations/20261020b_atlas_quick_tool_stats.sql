-- 20261020b_atlas_quick_tool_stats — what Atlas's quick step learns per user (TASK-140 Q3/Q4).
--   One row per (team, user, tool): uses in full Atlas turns, hits and misses of the quick step. The quick set of a
--   user = base tools + their top tools; a tool with misses >= 3 and a miss rate > 30% leaves their set.
--   atlas_quick_tool_bump() increments atomically. Written by vpt-server (service role) only.
-- Idempotent. Apply to every database the release reaches. The code works without it: every stats call fails soft.
-- Twin: setup/db/schema/075_atlas_quick_tool_stats.sql. Inverse: 20261020b_atlas_quick_tool_stats_rollback.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS public.atlas_quick_tool_stats (
    team_id     UUID NOT NULL,
    user_id     TEXT NOT NULL,
    tool        TEXT NOT NULL,
    uses        INTEGER NOT NULL DEFAULT 0,
    hits        INTEGER NOT NULL DEFAULT 0,
    misses      INTEGER NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (team_id, user_id, tool)
);

COMMENT ON TABLE public.atlas_quick_tool_stats IS
    'TASK-140 Q3/Q4: per user and team, how often each quick-step tool was used in full Atlas turns (uses) and how often the quick step got it right (hits) or wrong (misses). Every read filters by team_id.';

CREATE OR REPLACE FUNCTION public.atlas_quick_tool_bump(
    p_team_id UUID, p_user_id TEXT, p_tool TEXT, p_uses INTEGER, p_hits INTEGER, p_misses INTEGER
) RETURNS VOID
LANGUAGE sql AS $$
    INSERT INTO public.atlas_quick_tool_stats AS s (team_id, user_id, tool, uses, hits, misses, updated_at)
    VALUES (p_team_id, p_user_id, p_tool, p_uses, p_hits, p_misses, NOW())
    ON CONFLICT (team_id, user_id, tool) DO UPDATE
        SET uses = s.uses + EXCLUDED.uses,
            hits = s.hits + EXCLUDED.hits,
            misses = s.misses + EXCLUDED.misses,
            updated_at = NOW();
$$;

ALTER TABLE public.atlas_quick_tool_stats ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_atlas_quick_tool_stats" ON public.atlas_quick_tool_stats;
CREATE POLICY "service_role_all_atlas_quick_tool_stats" ON public.atlas_quick_tool_stats
    FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.atlas_quick_tool_stats FROM anon, authenticated;
REVOKE ALL ON FUNCTION public.atlas_quick_tool_bump(UUID, TEXT, TEXT, INTEGER, INTEGER, INTEGER) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.atlas_quick_tool_bump(UUID, TEXT, TEXT, INTEGER, INTEGER, INTEGER) TO service_role;

COMMIT;
