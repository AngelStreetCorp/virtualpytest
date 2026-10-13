-- ============================================================================
-- FLEET HEALTH TABLE
-- One row per device per fleet-health run (scripts/fleet_health_report.py on the
-- server VM — GOAL-04). Two runs write here, told apart by run_kind:
--   nightly — vpt-fleet-health.timer, daily 07:00, AI analysis + markdown report
--   live    — vpt-fleet-health-live.timer, every 10 min, pruned after 24h
-- All rows of a single run share the same generated_at (batch timestamp), so
-- "the latest run" is SELECT max(generated_at) ... WHERE run_kind = <kind>. The markdown report stays the
-- human artifact (MinIO); this table is the queryable history that the
-- vpt-fleet-health Grafana dashboard reads.
-- ============================================================================

CREATE TABLE IF NOT EXISTS fleet_health (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    generated_at TIMESTAMPTZ NOT NULL,          -- uniform per run (batch timestamp)
    run_date DATE NOT NULL,
    server TEXT NOT NULL,                       -- backend server the host registers on
    host_name TEXT NOT NULL,
    device_id TEXT NOT NULL,
    device_name TEXT,
    device_model TEXT,
    verdict TEXT NOT NULL CHECK (verdict IN ('OK', 'IDLE', 'DEGRADED', 'DOWN', 'UNKNOWN')),
    issue_since TIMESTAMPTZ,                    -- oldest open incident start (NULL = none)
    reason TEXT,                                -- layer-aware explanation
    ai_analysis TEXT,                           -- optional per-device AI diagnosis
    open_incidents JSONB NOT NULL DEFAULT '{}', -- {incident_type: start_iso}
    incidents_24h JSONB NOT NULL DEFAULT '{}',  -- {incident_type: count}
    last_script_name TEXT,
    last_script_success BOOLEAN,
    last_script_at TIMESTAMPTZ,
    report_url TEXT,                            -- presigned URL of the run's markdown report
    run_kind TEXT NOT NULL DEFAULT 'nightly'    -- nightly | live (see header)
        CHECK (run_kind IN ('nightly', 'live')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_fleet_health_generated_at ON fleet_health (generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_fleet_health_device ON fleet_health (host_name, device_id, generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_fleet_health_run_date ON fleet_health (run_date DESC);
CREATE INDEX IF NOT EXISTS idx_fleet_health_run_kind ON fleet_health (run_kind, generated_at DESC);

ALTER TABLE fleet_health ENABLE ROW LEVEL SECURITY;

-- Matches the monitoring-table policy convention (005_monitoring_analytics.sql)
CREATE POLICY "fleet_health_access_policy" ON fleet_health
FOR ALL
TO public
USING (true);
