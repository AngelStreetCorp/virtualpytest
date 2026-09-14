-- ============================================================================
-- Expand get_tree_metrics_optimized across the full subtree hierarchy
-- ============================================================================
-- Goto-panel ETA on the editor was showing "unknown" whenever a navigation
-- path crossed into a subtree (e.g. ENTRY → apps_appletv: the first 4 hops
-- live on the root tree, the last 2 live on the "apps" subtree).
--
-- The RPC was filtering edge_metrics / node_metrics with tree_id = p_tree_id,
-- so any edge stored under a child tree_id was excluded from preloadedMetrics
-- and the frontend's `eta.measured < eta.total` branch took over. The trigger
-- itself was correct — rows were aggregating fine, the read just couldn't
-- see them.
--
-- Fix: walk navigation_trees recursively from p_tree_id, collect every
-- descendant tree_id once, then use `tree_id = ANY(...)` on every metrics
-- read AND on the inner kpi_report_url lookup. p_tree_id staying the root
-- means existing callers (NavigationEditor combined endpoint, edge-selection
-- panel) get the full hierarchy automatically.
--
-- Confidence aggregation now spans the hierarchy too, which matches what
-- /server/metrics/tree/<root> already returns via get_complete_tree_hierarchy.

CREATE OR REPLACE FUNCTION public.get_tree_metrics_optimized(
    p_tree_id uuid,
    p_team_id uuid,
    p_variant text DEFAULT NULL
)
RETURNS json
LANGUAGE plpgsql
STABLE SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_node_metrics JSON;
    v_edge_metrics JSON;
    v_global_confidence NUMERIC;
    v_confidence_distribution JSON;
    v_all_confidences NUMERIC[];
    v_tree_ids uuid[];
BEGIN
    -- Collect the root tree plus every descendant in one pass. Cheap: depth is
    -- bounded by the check_tree_depth constraint (<= 5) and idx_navigation_trees_parent_tree
    -- covers the recursive join.
    WITH RECURSIVE descendants AS (
        SELECT id
        FROM public.navigation_trees
        WHERE id = p_tree_id
        UNION ALL
        SELECT nt.id
        FROM public.navigation_trees nt
        JOIN descendants d ON nt.parent_tree_id = d.id
    )
    SELECT array_agg(id) INTO v_tree_ids FROM descendants;

    SELECT json_object_agg(
        node_id,
        json_build_object(
            'volume', total_executions,
            'success_rate', success_rate::float,
            'avg_verification_time', avg_verification_time_ms,
            'confidence', CASE
                WHEN total_executions = 0 THEN 0.0
                WHEN total_executions < 10 THEN success_rate::float * (total_executions / 10.0)
                ELSE success_rate::float
            END
        )
    )
    INTO v_node_metrics
    FROM public.node_metrics
    WHERE team_id = p_team_id
      AND tree_id = ANY(v_tree_ids)
      AND variant IS NOT DISTINCT FROM p_variant;

    SELECT json_object_agg(
        edge_id || COALESCE('#' || action_set_id, ''),
        json_build_object(
            'volume', total_executions,
            'success_rate', success_rate::float,
            'avg_action_time', avg_action_time_ms,
            'avg_kpi_ms', avg_kpi_ms,
            'kpi_volume', total_kpi_measurements,
            'kpi_report_url', (
                SELECT er.kpi_report_url
                FROM public.execution_results er
                WHERE er.team_id = p_team_id
                  AND er.tree_id = ANY(v_tree_ids)
                  AND er.edge_id = em.edge_id
                  AND er.action_set_id = em.action_set_id
                  AND er.variant IS NOT DISTINCT FROM em.variant
                  AND er.kpi_report_url IS NOT NULL
                ORDER BY er.executed_at DESC
                LIMIT 1
            ),
            'confidence', CASE
                WHEN total_executions = 0 THEN 0.0
                WHEN total_executions < 10 THEN success_rate::float * (total_executions / 10.0)
                ELSE success_rate::float
            END
        )
    )
    INTO v_edge_metrics
    FROM public.edge_metrics em
    WHERE em.team_id = p_team_id
      AND em.tree_id = ANY(v_tree_ids)
      AND em.variant IS NOT DISTINCT FROM p_variant;

    SELECT array_agg(confidence)
    INTO v_all_confidences
    FROM (
        SELECT
            CASE
                WHEN total_executions = 0 THEN 0.0
                WHEN total_executions < 10 THEN success_rate::float * (total_executions / 10.0)
                ELSE success_rate::float
            END as confidence
        FROM public.node_metrics
        WHERE team_id = p_team_id AND tree_id = ANY(v_tree_ids)
          AND variant IS NOT DISTINCT FROM p_variant
        UNION ALL
        SELECT
            CASE
                WHEN total_executions = 0 THEN 0.0
                WHEN total_executions < 10 THEN success_rate::float * (total_executions / 10.0)
                ELSE success_rate::float
            END as confidence
        FROM public.edge_metrics
        WHERE team_id = p_team_id AND tree_id = ANY(v_tree_ids)
          AND variant IS NOT DISTINCT FROM p_variant
    ) all_conf;

    IF v_all_confidences IS NOT NULL AND array_length(v_all_confidences, 1) > 0 THEN
        SELECT AVG(c) INTO v_global_confidence FROM unnest(v_all_confidences) c;
    ELSE
        v_global_confidence := 0.0;
    END IF;

    SELECT json_build_object(
        'high', COUNT(*) FILTER (WHERE c >= 0.8),
        'medium', COUNT(*) FILTER (WHERE c >= 0.5 AND c < 0.8),
        'low', COUNT(*) FILTER (WHERE c >= 0.1 AND c < 0.5),
        'untested', COUNT(*) FILTER (WHERE c < 0.1)
    )
    INTO v_confidence_distribution
    FROM unnest(v_all_confidences) c;

    RETURN json_build_object(
        'success', true,
        'variant', p_variant,
        'nodes', COALESCE(v_node_metrics, '{}'::json),
        'edges', COALESCE(v_edge_metrics, '{}'::json),
        'global_confidence', COALESCE(v_global_confidence, 0.0),
        'confidence_distribution', COALESCE(v_confidence_distribution,
            json_build_object('high', 0, 'medium', 0, 'low', 0, 'untested', 0))
    );
END;
$$;

COMMENT ON FUNCTION public.get_tree_metrics_optimized(uuid, uuid, text) IS
    'Aggregated metrics for a tree filtered by run scope (variant). NULL p_variant = base-only. p_tree_id is the entry point — the function expands to the full subtree hierarchy via parent_tree_id, so cross-subtree paths (root → apps subtree → ...) all surface in a single payload. Edge entries also include the latest kpi_report_url for that (edge, action_set, variant).';
