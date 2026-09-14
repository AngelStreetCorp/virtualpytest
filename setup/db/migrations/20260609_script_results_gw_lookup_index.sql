-- ============================================================================
-- 20260609_script_results_gw_lookup_index.sql
--
-- Grafana dashboard performance — the RIGHT fix: an index, not a materialized view.
--
-- The SRI dashboards enrich rows with the latest gw_info for the same host via a
-- correlated `LEFT JOIN LATERAL` (script_name='gw_info' AND host_name=? AND
-- started_at<=? ORDER BY started_at DESC LIMIT 1). Each panel already filters to
-- ONE script_name + the picker's time window, so the LATERAL only runs over a
-- small slice — it just needs an index to be a single seek instead of a bitmap-AND.
--
-- Measured on the dev DB: the live enriched query over all dns history went
-- 2213 ms -> 81 ms with this index. So dashboards query script_results LIVE
-- (always fresh, zero background cost). No materialized view, no refresh.

-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_sr_script_host_started
  ON script_results (script_name, host_name, started_at DESC);