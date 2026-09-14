-- ============================================================================
-- script_results (script_name, success) index — Grafana variable queries
-- ============================================================================
-- Context: BUG-0074 (Grafana template variables erroring intermittently on a
-- large customer DB). The variable queries have the shape
--   SELECT DISTINCT COALESCE(metadata->>'firmware_version', 'Unknown')
--   FROM script_results WHERE script_name = 'gw_info' AND success = true
-- With only idx_script_results_script_name, Postgres bitmap-scans every
-- script_name match and applies `success` as a heap filter — on the customer
-- DB (1.7M rows, 93K gw_info) that fetched ~14K non-success rows for nothing.
--
-- This index lets the WHERE clause be answered from the index (Index Cond on
-- both columns, no filter recheck). Measured on the customer DB: ~15% fewer
-- heap pages read. It is a modest improvement, NOT the fix for BUG-0074 —
-- the query is still dominated by reading the matching rows' jsonb metadata
-- (79K rows / 56K heap pages ≈ 1.3 s), and the actual failure was a
-- shared-memory exhaustion (see 20260910b). Kept because it is cheap,
-- harmless, and correct for this predicate.
--
-- Plain (non-CONCURRENT) build so it runs through the standard migration
-- flow, which wraps each file in a transaction. Reads stay available; writes
-- to script_results wait for the build (seconds on ~1.7M rows). Apply at a
-- quiet moment.

CREATE INDEX IF NOT EXISTS idx_script_results_script_name_success
    ON public.script_results (script_name, success);

COMMENT ON INDEX public.idx_script_results_script_name_success IS
    'script_name + success predicate (Grafana template variable queries): both columns in the Index Cond instead of a heap filter on success.';
