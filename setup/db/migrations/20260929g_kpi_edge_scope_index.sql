-- ============================================================================
-- BUG-0189 - make the per-edge kpi_report_url probe actually index-usable
-- ============================================================================
-- BUG-0001 (20260715_kpi_report_url_edge_lookup_index.sql) added
--     idx_execution_results_kpi_edge_lookup
--       (team_id, edge_id, action_set_id, variant, executed_at DESC)
--       WHERE kpi_report_url IS NOT NULL
-- to turn the per-edge kpi_report_url subquery inside get_tree_metrics_optimized()
-- into "a top-1 index probe". It never could. The subquery scopes the lookup with
--     er.variant IS NOT DISTINCT FROM em.variant
-- which is NOT an indexable equality, so `variant` drops out of the Index Cond and
-- becomes a post-scan Filter. Once it does, the index can no longer return rows in
-- executed_at DESC order for the matching subset, so ORDER BY ... LIMIT 1 never
-- short-circuits: Postgres reads EVERY kpi row of that edge and top-N sorts it,
-- once per edge_metrics row in scope.
--
-- Measured on a customer DB (execution_results 2.9M rows, 46 edges in scope):
--   before  13623 index entries scanned per edge, 553344 buffers (~4.3 GB of I/O),
--           1865 ms for the edge aggregation. The RPC averaged 3018 ms and peaked
--           at 7908 ms against authenticator's 8 s statement_timeout, so it
--           intermittently died with 57014 and surfaced as a 500 on
--           GET /server/navigationTrees/getTreeByUserInterfaceId?include_metrics=true
--           (blank Navigation editor, no metrics).
--   after   1.0 ms for the same aggregation; the RPC 5 ms avg / 6 ms max.
--
-- The fix has two halves that only work together:
--   1. index the scope as COALESCE(variant,'') so all four equality columns sit
--      ahead of executed_at DESC;
--   2. use the SAME expression in the function - an expression index is only
--      usable when the query text matches it.
-- Applying half 1 alone leaves the probe at ~670 ms (it still walks the whole
-- per-edge history when no row matches the scope, which is the common case).
--
-- Also drops idx_execution_results_kpi_report: it indexes the URL *string*
-- (kpi_report_url), and nothing ever looks a row up by URL value - the RPC only
-- returns it. 176 MB plus write amplification on every execution insert, zero reads.
--
-- DEPLOY NOTES
--   * Built/dropped CONCURRENTLY so it never blocks execution_results writes.
--     CONCURRENTLY cannot run inside a transaction block - run this file
--     standalone (do NOT wrap it in BEGIN/COMMIT, and note the Supabase CLI
--     rejects CONCURRENTLY: for CLI installs drop the keyword, accepting the
--     lock for the duration of the build).
--   * ANALYZE execution_results afterwards if the table has never been analyzed
--     (the customer DB had last_analyze = last_autoanalyze = NULL on a 2.9M-row
--     table, so every plan touching it was a guess).
--   * DB-only: no application change is needed, and the RPC's signature and
--     payload are unchanged, so old builds keep working.

-- The COALESCE(variant,'') sentinel conflates a literal empty-string variant with
-- base scope (NULL). Neither table has ever stored '' - fail loudly instead of
-- silently mixing two run scopes if that ever changes.
DO $sentinel$
BEGIN
    IF EXISTS (SELECT 1 FROM public.execution_results WHERE variant = '')
       OR EXISTS (SELECT 1 FROM public.edge_metrics WHERE variant = '') THEN
        RAISE EXCEPTION 'variant = '''' rows exist: the COALESCE(variant, '''') '
                        'sentinel would conflate them with base scope';
    END IF;
END
$sentinel$;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_execution_results_kpi_edge_scope
    ON public.execution_results
       (team_id, edge_id, action_set_id, (COALESCE(variant, '')), executed_at DESC)
    WHERE kpi_report_url IS NOT NULL;

COMMENT ON INDEX public.idx_execution_results_kpi_edge_scope IS
    'Top-1 probe for the per-edge latest-kpi_report_url subquery in get_tree_metrics_optimized(). The scope is keyed as COALESCE(variant,'''') so all four equality columns precede executed_at DESC and the LIMIT 1 stops at the first row; the function must use the same expression.';

-- Same body as before, with ONE line changed in the kpi_report_url subquery so it
-- matches the index expression above. Kept byte-identical to
-- setup/db/schema/005_monitoring_analytics.sql.
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
                  -- Indexable equality (NOT `IS NOT DISTINCT FROM`, which the
                  -- planner cannot match to an index) so this stays a top-1 probe
                  -- on idx_execution_results_kpi_edge_scope. See BUG-0189.
                  AND COALESCE(er.variant, '') = COALESCE(em.variant, '')
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

-- Superseded by idx_execution_results_kpi_edge_scope (same access path, strictly
-- better): drop only after the index above reports indisvalid = true.
DROP INDEX CONCURRENTLY IF EXISTS public.idx_execution_results_kpi_edge_lookup;

-- Indexes the URL string; never read by any query.
DROP INDEX CONCURRENTLY IF EXISTS public.idx_execution_results_kpi_report;
