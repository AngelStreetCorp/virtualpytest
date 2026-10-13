-- 20261001e_infra_status.sql
-- service_status + vm_metrics: the /status page's data kept as history for the
-- "System Service Status" Grafana dashboard. Written by the backend server's
-- infra-status collector; VM resources come from infra/vm_agent/.
--
-- Canonical twin: setup/db/schema/057_infra_status.sql. Idempotent.
-- Inverse: 20261001e_infra_status_rollback.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS service_status (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    checked_at TIMESTAMPTZ NOT NULL,            -- uniform per collector run
    server_name TEXT NOT NULL,                  -- collector that wrote the row (SERVER_NAME)
    vm TEXT NOT NULL,                           -- group shown on /status: server, database, storage, …
    component TEXT NOT NULL,                    -- e.g. vpt-server, redis, supabase_db_supabase, agent
    status TEXT NOT NULL CHECK (status IN ('ok', 'degraded', 'down', 'unknown')),
    detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_service_status_checked_at ON service_status (checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_service_status_component ON service_status (vm, component, checked_at DESC);

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
ALTER TABLE vm_metrics ENABLE ROW LEVEL SECURITY;

-- Matches the monitoring-table policy convention (040_fleet_health.sql); the
-- browser roles get no table grant at all (049_authenticated_read_only.sql).
DROP POLICY IF EXISTS "service_status_access_policy" ON service_status;
CREATE POLICY "service_status_access_policy" ON service_status FOR ALL TO public USING (true);
DROP POLICY IF EXISTS "vm_metrics_access_policy" ON vm_metrics;
CREATE POLICY "vm_metrics_access_policy" ON vm_metrics FOR ALL TO public USING (true);

REVOKE ALL ON service_status, vm_metrics FROM anon, authenticated;
GRANT ALL ON service_status, vm_metrics TO service_role;

-- 90-day retention: ~15 rows a minute per collector is history enough for
-- availability %, and keeps the tables small.
CREATE OR REPLACE FUNCTION retention.cleanup_infra_status()
RETURNS TABLE(deleted_count INTEGER, table_name TEXT, retention_days INTEGER)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_status INTEGER;
  v_metrics INTEGER;
BEGIN
  DELETE FROM public.service_status WHERE checked_at < NOW() - INTERVAL '90 days';
  GET DIAGNOSTICS v_status = ROW_COUNT;
  DELETE FROM public.vm_metrics WHERE timestamp < NOW() - INTERVAL '90 days';
  GET DIAGNOSTICS v_metrics = ROW_COUNT;
  RETURN QUERY SELECT v_status, 'service_status'::TEXT, 90
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

COMMIT;

NOTIFY pgrst, 'reload schema';
