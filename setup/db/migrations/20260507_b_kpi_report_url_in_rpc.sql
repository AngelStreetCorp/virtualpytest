-- ============================================================================
-- Add latest kpi_report_url to get_tree_metrics_optimized per-edge payload
-- ============================================================================
-- Lets the Edge Selection panel's KPI chip become a one-click link to the
-- most recent KPI measurement report for the selected (edge, action_set,
-- variant) — no extra round-trip, no new endpoint, no Supabase client in
-- the frontend. The URL travels with the metrics already loaded for the
-- panel.
--
-- The subquery uses idx_execution_results_kpi_report (partial index on
-- kpi_report_url IS NOT NULL) plus the variant attribution index, so each
-- edge in the result is a fast index lookup of the most recent row.

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
BEGIN
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
      AND tree_id = p_tree_id
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
                  AND er.tree_id = p_tree_id
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
      AND em.tree_id = p_tree_id
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
        WHERE team_id = p_team_id AND tree_id = p_tree_id
          AND variant IS NOT DISTINCT FROM p_variant
        UNION ALL
        SELECT
            CASE
                WHEN total_executions = 0 THEN 0.0
                WHEN total_executions < 10 THEN success_rate::float * (total_executions / 10.0)
                ELSE success_rate::float
            END as confidence
        FROM public.edge_metrics
        WHERE team_id = p_team_id AND tree_id = p_tree_id
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
    'Aggregated metrics for a tree filtered by run scope (variant). NULL p_variant = base-only. Edge entries also include the latest kpi_report_url for that (edge, action_set, variant) so the frontend KPI chip can link directly to the most recent report.';
