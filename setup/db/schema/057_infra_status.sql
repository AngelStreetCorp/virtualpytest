-- ============================================================================
-- INFRA STATUS TABLES
-- What the /status page shows live, kept as history so Grafana can show it
-- ("System Service Status" dashboard, infra/monitoring/grafana/dashboards/
-- system-service-status.json).
--
-- Written by the backend server's infra-status collector
-- (backend_server/src/lib/server/infra_status_collector.py), which checks once a
-- minute but stores little, so the tables stay small:
--   service_status_current — one live row per component (the server's own services,
--                    Redis, DB backup, every service a VM agent reports), overwritten
--                    every minute.
--   service_status — change log: a row only when a component's status changes, plus a
--                    'down' / 'no report' row when reports stopped for 3+ minutes.
--   vm_metrics     — CPU / RAM / disk / load / uptime of the infra VMs (database,
--                    storage, frontend, proxy, …) every 5 minutes, pulled from the VM
--                    agent (infra/vm_agent/vpt_vm_agent.py) on each VM.
-- Hosts keep reporting into system_metrics as before; these tables never hold
-- host rows, so the host dashboards are unaffected.
--
-- Status: ok = running · stopped = not running, switched off · degraded = starting /
-- unhealthy · down = failing (crashed, stuck, missing) · unknown = can't tell.
--
-- A component that stops being written is DOWN: the dashboard treats a live row
-- older than 3 minutes as stale, so a VM that is off (no agent answer) or a server
-- that cannot reach the database (no row at all) both show.
-- ============================================================================

CREATE TABLE IF NOT EXISTS service_status (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    checked_at TIMESTAMPTZ NOT NULL,            -- when the status changed (collector run time)
    server_name TEXT NOT NULL,                  -- collector that wrote the row (SERVER_NAME)
    vm TEXT NOT NULL,                           -- group shown on /status: server, database, storage, …
    component TEXT NOT NULL,                    -- e.g. vpt-server, redis, supabase_db_supabase, agent
    status TEXT NOT NULL CHECK (status IN ('ok', 'stopped', 'degraded', 'down', 'unknown')),
    detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_service_status_checked_at ON service_status (checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_service_status_component ON service_status (vm, component, checked_at DESC);

CREATE TABLE IF NOT EXISTS service_status_current (
    server_name TEXT NOT NULL,
    vm TEXT NOT NULL,
    component TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok', 'stopped', 'degraded', 'down', 'unknown')),
    detail TEXT,
    checked_at TIMESTAMPTZ NOT NULL,            -- last report (older than 3 min = STALE)
    since TIMESTAMPTZ NOT NULL,                 -- when the current status started
    PRIMARY KEY (server_name, vm, component)
);

CREATE TABLE IF NOT EXISTS vm_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL,
    server_name TEXT NOT NULL,                  -- collector that pulled the agent
    vm TEXT NOT NULL,                           -- database, storage, frontend, proxy, …
    hostname TEXT,                              -- what the VM calls itself
    cpu_percent NUMERIC,
    memory_percent NUMERIC,
    memory_used_gb NUMERIC,
    memory_total_gb NUMERIC,
    disk_percent NUMERIC,
    disk_used_gb NUMERIC,
    disk_total_gb NUMERIC,
    load_average_1m NUMERIC(6,2),
    cpu_count INTEGER,
    uptime_seconds BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vm_metrics_vm_timestamp ON vm_metrics (vm, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_vm_metrics_timestamp ON vm_metrics (timestamp DESC);

ALTER TABLE service_status ENABLE ROW LEVEL SECURITY;
ALTER TABLE service_status_current ENABLE ROW LEVEL SECURITY;
ALTER TABLE vm_metrics ENABLE ROW LEVEL SECURITY;

-- Matches the monitoring-table policy convention (040_fleet_health.sql); the
-- browser roles get no table grant at all (049_authenticated_read_only.sql).
DROP POLICY IF EXISTS "service_status_access_policy" ON service_status;
CREATE POLICY "service_status_access_policy" ON service_status FOR ALL TO public USING (true);
DROP POLICY IF EXISTS "service_status_current_access_policy" ON service_status_current;
CREATE POLICY "service_status_current_access_policy" ON service_status_current FOR ALL TO public USING (true);
DROP POLICY IF EXISTS "vm_metrics_access_policy" ON vm_metrics;
CREATE POLICY "vm_metrics_access_policy" ON vm_metrics FOR ALL TO public USING (true);

REVOKE ALL ON service_status, service_status_current, vm_metrics FROM anon, authenticated;
GRANT ALL ON service_status, service_status_current, vm_metrics TO service_role;

-- Retention: the change log is a few rows a day, kept a year; vm_metrics (one row per
-- VM every 5 minutes, ~0.8 MB/day for 5 VMs) is kept 90 days.
CREATE OR REPLACE FUNCTION retention.cleanup_infra_status()
RETURNS TABLE(deleted_count INTEGER, table_name TEXT, retention_days INTEGER)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_status INTEGER;
  v_metrics INTEGER;
BEGIN
  DELETE FROM public.service_status WHERE checked_at < NOW() - INTERVAL '365 days';
  GET DIAGNOSTICS v_status = ROW_COUNT;
  DELETE FROM public.vm_metrics WHERE timestamp < NOW() - INTERVAL '90 days';
  GET DIAGNOSTICS v_metrics = ROW_COUNT;
  RETURN QUERY SELECT v_status, 'service_status'::TEXT, 365
         UNION ALL SELECT v_metrics, 'vm_metrics'::TEXT, 90;
END;
$$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
    PERFORM cron.unschedule(jobid) FROM cron.job WHERE jobname = 'cleanup-infra-status';
    PERFORM cron.schedule('cleanup-infra-status', '15 2 * * *', 'SELECT retention.cleanup_infra_status()');
  END IF;
END $$;
