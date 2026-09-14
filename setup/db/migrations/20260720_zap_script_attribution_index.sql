-- Index for the "Automatic Zapping Events" script-attribution lookup.
--
-- Automatic zaps are recorded with script_result_id = NULL (zapping_detector_utils
-- hardcodes it — the monitor detects them out-of-band, with no handle on the run
-- that caused them). The dashboard therefore recovers the driving script by time
-- overlap: the script_results row for the same host+device whose [started_at,
-- completed_at] window contains the zap.
--
-- The existing idx_sr_script_host_started leads with script_name, which this
-- lookup does not filter on, so it degraded to a scan of script_results per zap
-- row. Measured on the dev DB over 161 zaps: 134 ms -> 1.3 ms with this index
-- (seq scan per row -> single index seek). Same reasoning as
-- 20260609_script_results_gw_lookup_index.sql.

CREATE INDEX IF NOT EXISTS idx_sr_host_device_started
  ON script_results (host_name, device_name, started_at DESC);

-- Every panel on the zapping dashboard filters and orders zap_results by
-- created_at, which had no index — only execution_date did, and nothing queries
-- that. Without this the 200-row window is a seq scan + sort of the whole table.
CREATE INDEX IF NOT EXISTS idx_zap_results_created_at
  ON zap_results (created_at DESC);
