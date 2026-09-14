-- ============================================================================
-- Fix statement-timeout (57014) on get_tree_metrics_optimized for large trees
-- ============================================================================
-- Symptom: /remote-control (NavigationEditor) calls
--   getTreeByUserInterfaceId/<id>?include_metrics=true
-- which runs get_tree_metrics_optimized(). On an interface with a large
-- execution history (e.g. example_tv) the RPC times out with
--   {'code': '57014', 'message': 'canceling statement due to statement timeout'}
-- A freshly *duplicated* interface loads fine — it has zero execution_results
-- rows, so the offending subquery returns instantly.
--
-- Root cause: the per-edge correlated subquery that fetches the latest
-- kpi_report_url (added in 20260507_b, widened to the subtree hierarchy in
-- 20260508_e) filters execution_results by edge_id / action_set_id / variant
-- and takes ORDER BY executed_at DESC LIMIT 1 — once per edge_metrics row.
-- execution_results has NO index on edge_id/action_set_id, so each edge does a
-- scan + sort of the raw history. N edges * large history = timeout.
--
-- The 20260507_b comment already claimed "each edge is a fast index lookup of
-- the most recent row" — but that index never existed. This adds it.
--
-- Index design mirrors the subquery predicate exactly:
--   team_id, edge_id, action_set_id, variant  -> equality probe
--   executed_at DESC                          -> satisfies ORDER BY ... LIMIT 1
--   WHERE kpi_report_url IS NOT NULL          -> matches the subquery filter,
--                                                keeps the index small
-- tree_id = ANY(v_tree_ids) stays a cheap residual filter over the already
-- narrow per-edge slice (edge_id is a globally-unique id, so this barely
-- widens the candidate set).
--
-- Built CONCURRENTLY so it does not block writes to execution_results on prod.
-- CONCURRENTLY cannot run inside a transaction block — run this file on its own
-- (do NOT wrap it in BEGIN/COMMIT).

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_execution_results_kpi_edge_lookup
    ON public.execution_results (team_id, edge_id, action_set_id, variant, executed_at DESC)
    WHERE kpi_report_url IS NOT NULL;

COMMENT ON INDEX public.idx_execution_results_kpi_edge_lookup IS
    'Supports the per-edge latest-kpi_report_url subquery in get_tree_metrics_optimized(). Turns each per-edge lookup into a top-1 index probe, preventing statement timeouts on trees with large execution history.';
