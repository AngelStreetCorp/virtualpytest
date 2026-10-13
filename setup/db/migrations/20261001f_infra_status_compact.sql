-- 20261001f_infra_status_compact.sql
-- Shrink the infra-status history: checking every minute stays, storing every minute
-- does not (it would have reached ~1.3 GB in 90 days on a 1.2 GB database).
--   service_status_current — new: one live row per component, overwritten every minute
--   service_status         — now a change log: a row only when a status changes
--   vm_metrics             — one row per VM every 5 minutes (was every minute)
-- Existing rows are compacted the same way. Idempotent — run it again after deploying
-- the new collector to compact what the old one wrote in between.
--
-- Canonical twin: setup/db/schema/057_infra_status.sql.
-- Inverse: 20261001f_infra_status_compact_rollback.sql (drops the live table only; the
-- deleted per-minute rows are not restored).

BEGIN;

CREATE TABLE IF NOT EXISTS service_status_current (
    server_name TEXT NOT NULL,
    vm TEXT NOT NULL,
    component TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok', 'degraded', 'down', 'unknown')),
    detail TEXT,
    checked_at TIMESTAMPTZ NOT NULL,            -- last report (older than 3 min = STALE)
    since TIMESTAMPTZ NOT NULL,                 -- when the current status started
    PRIMARY KEY (server_name, vm, component)
);

ALTER TABLE service_status_current ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_status_current_access_policy" ON service_status_current;
CREATE POLICY "service_status_current_access_policy" ON service_status_current FOR ALL TO public USING (true);
REVOKE ALL ON service_status_current FROM anon, authenticated;
GRANT ALL ON service_status_current TO service_role;

COMMENT ON COLUMN service_status.checked_at IS 'when the status changed (collector run time)';

-- Keep only the rows where a component's status differs from its previous row.
DELETE FROM service_status s
USING (
    SELECT id, status,
           lag(status) OVER (PARTITION BY server_name, vm, component ORDER BY checked_at) AS prev
    FROM service_status
) x
WHERE s.id = x.id AND x.prev = x.status;

-- vm_metrics: keep the 5-minute marks only.
DELETE FROM vm_metrics WHERE extract(minute FROM timestamp)::int % 5 <> 0;

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

COMMIT;

NOTIFY pgrst, 'reload schema';
