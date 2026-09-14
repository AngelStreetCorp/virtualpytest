-- Move final_wait_time and threshold off the edge and onto each action_set
-- so each direction (forward / reverse) carries its own value.
--
-- Before: navigation_edges.final_wait_time (column) and navigation_edges.data->>'threshold'
--         were single, shared across both directions.
-- After:  every action_set entry in navigation_edges.action_sets has its own
--         final_wait_time and threshold fields; the edge-level column / JSON key
--         are removed.
--
-- Idempotent: re-running first checks if the column still exists / data still
-- has the threshold key, copies forward only what's still there. Safe to re-run.

BEGIN;

-- 1. Backfill final_wait_time into every action_set element from the column.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'navigation_edges'
          AND column_name = 'final_wait_time'
    ) THEN
        UPDATE public.navigation_edges
        SET action_sets = (
            SELECT jsonb_agg(
                COALESCE(elem, '{}'::jsonb) ||
                jsonb_build_object('final_wait_time', COALESCE(navigation_edges.final_wait_time, 0))
            )
            FROM jsonb_array_elements(navigation_edges.action_sets) AS elem
        )
        WHERE jsonb_typeof(action_sets) = 'array';
    END IF;
END $$;

-- 2. Backfill threshold into every action_set element from data.threshold (if set).
UPDATE public.navigation_edges
SET action_sets = (
    SELECT jsonb_agg(
        COALESCE(elem, '{}'::jsonb) ||
        jsonb_build_object('threshold', (data->>'threshold')::int)
    )
    FROM jsonb_array_elements(action_sets) AS elem
)
WHERE jsonb_typeof(action_sets) = 'array'
  AND data ? 'threshold'
  AND (data->>'threshold') ~ '^-?\d+$';

-- 3. Strip the threshold key from data JSONB now that it lives per action_set.
UPDATE public.navigation_edges
SET data = data - 'threshold'
WHERE data ? 'threshold';

-- 4. The materialized view mv_full_navigation_trees selects
--    navigation_edges.final_wait_time. Rebuild it without the column before
--    dropping so the DROP doesn't fail on the dependency.
DROP MATERIALIZED VIEW IF EXISTS public.mv_full_navigation_trees;

CREATE MATERIALIZED VIEW public.mv_full_navigation_trees AS
SELECT
    t.id AS tree_id,
    t.team_id,
    json_build_object(
        'success', true,
        'tree', row_to_json(t.*),
        'nodes', COALESCE(
            (SELECT json_agg(n ORDER BY n.created_at)
             FROM (
                SELECT
                    id,
                    tree_id,
                    node_id,
                    node_type,
                    label,
                    position_x,
                    position_y,
                    data,
                    style,
                    team_id,
                    has_subtree,
                    subtree_count,
                    verifications,
                    hidden_in_base,
                    created_at,
                    updated_at
                FROM public.navigation_nodes
                WHERE tree_id = t.id
                AND team_id = t.team_id
             ) n),
            '[]'::json
        ),
        'edges', COALESCE(
            (SELECT json_agg(e ORDER BY e.created_at)
             FROM (
                SELECT
                    id,
                    tree_id,
                    edge_id,
                    source_node_id,
                    target_node_id,
                    label,
                    data,
                    team_id,
                    action_sets,
                    hidden_in_base,
                    default_action_set_id,
                    created_at,
                    updated_at
                FROM public.navigation_edges
                WHERE tree_id = t.id
                AND team_id = t.team_id
             ) e),
            '[]'::json
        )
    ) AS full_tree_data,
    now() AS last_refreshed
FROM public.navigation_trees t;

CREATE UNIQUE INDEX idx_mv_full_trees_tree_team
    ON public.mv_full_navigation_trees(tree_id, team_id);
CREATE INDEX idx_mv_full_navigation_trees_tree_id
    ON public.mv_full_navigation_trees(tree_id);
CREATE INDEX idx_mv_full_navigation_trees_team_id
    ON public.mv_full_navigation_trees(team_id);
CREATE INDEX idx_mv_full_navigation_trees_tree_team
    ON public.mv_full_navigation_trees(tree_id, team_id);

REFRESH MATERIALIZED VIEW public.mv_full_navigation_trees;

-- 5. Drop the edge-level final_wait_time column.
ALTER TABLE public.navigation_edges
    DROP COLUMN IF EXISTS final_wait_time;

COMMIT;
