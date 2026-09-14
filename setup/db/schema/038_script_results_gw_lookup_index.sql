-- VirtualPyTest — index for the gw_info as-of enrichment used by SRI dashboards.
--
-- The SRI dashboards (dns/ookla/superping/email/udp/windows/service-kpi) enrich
-- each row with the latest gw_info for the same host via a correlated LATERAL
-- (script_name='gw_info' AND host_name=? AND started_at<=? ORDER BY started_at
-- DESC LIMIT 1). This index turns that lookup into a single seek per row, so the
-- dashboards query script_results LIVE and stay fast (2213 ms -> 81 ms over all
-- dns history on the dev DB) — no materialized view, no refresh.
--
-- Depends on: 003_test_execution_tables.sql (script_results).
-- Canonical for fresh installs; the dated migration that adds it to an existing
-- DB (and removes the superseded script_results_enriched MV) is
-- setup/db/migrations/20260609_script_results_gw_lookup_index.sql.

CREATE INDEX IF NOT EXISTS idx_sr_script_host_started
  ON script_results (script_name, host_name, started_at DESC);
