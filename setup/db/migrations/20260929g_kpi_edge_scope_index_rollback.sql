-- ============================================================================
-- Rollback for 20260929g_kpi_edge_scope_index.sql (BUG-0189)
-- ============================================================================
-- Restores the pre-BUG-0189 index set and function body. Note this reinstates the
-- slow per-edge probe (see the forward migration for the numbers), so only run it
-- if the expression index itself caused a problem.
--
-- CONCURRENTLY cannot run inside a transaction block - run this file standalone.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_execution_results_kpi_edge_lookup
    ON public.execution_results (team_id, edge_id, action_set_id, variant, executed_at DESC)
    WHERE kpi_report_url IS NOT NULL;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_execution_results_kpi_report
    ON public.execution_results (kpi_report_url)
    WHERE kpi_report_url IS NOT NULL;

CREATE OR REPLACE FUNCTION public.get_tree_metrics_optimized(
    p_tree_id UUID,
    p_team_id UUID,
    p_variant TEXT DEFAULT NULL
)
RETURNS JSON
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
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
    -- p_tree_id is the entry point. Walk parent_tree_id recursively so cross-
    -- subtree paths (root → apps subtree → ...) all surface in one payload.
    -- Bounded by check_tree_depth (<= 5) and the parent_tree index.
    WITH RECURSIVE descendants AS (
        SELECT id FROM public.navigation_trees WHERE id = p_tree_id
        UNION ALL
        SELECT nt.id
        FROM public.navigation_trees nt
        JOIN descendants d ON nt.parent_tree_id = d.id
    )
    SELECT array_agg(id) INTO v_tree_ids FROM descendants;

    -- Filter by variant: NULL p_variant returns base-only rows
    -- (variant IS NULL). Each (variant) is a separate run scope.
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
            -- Latest kpi_report_url for this (edge, action_set, variant) so
            -- the Edge Selection panel's KPI chip can deep-link to the most
            -- recent report. NULL when no measurement has produced a report
            -- yet for this scope.
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
        WHERE team_id = p_team_id
          AND tree_id = ANY(v_tree_ids)
          AND variant IS NOT DISTINCT FROM p_variant

        UNION ALL

        SELECT
            CASE
                WHEN total_executions = 0 THEN 0.0
                WHEN total_executions < 10 THEN success_rate::float * (total_executions / 10.0)
                ELSE success_rate::float
            END as confidence
        FROM public.edge_metrics
        WHERE team_id = p_team_id
          AND tree_id = ANY(v_tree_ids)
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

DROP INDEX CONCURRENTLY IF EXISTS public.idx_execution_results_kpi_edge_scope;
