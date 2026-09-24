-- 20260917_analytics_views.sql
-- Applies the Monitoring > Analytics aggregates to an existing database.
-- Canonical definition: setup/db/schema/048_analytics_views.sql — keep the two in
-- step; this file is that one, applied to a database that already has data.
-- Idempotent: safe to re-run.
BEGIN;

-- ---------------------------------------------------------------------------
-- 0. Indexes the live-status views ride on
-- ---------------------------------------------------------------------------
-- Without these, "latest row per device" sorts every row in the roster window to
-- return 12: measured 16 479 rows quicksorted, 252 ms. With them plus the LATERAL
-- form below, each device's latest row is a single index descent — 81 ms total,
-- almost all of it the roster scan.
-- Plain CREATE INDEX (not CONCURRENTLY) so this stays inside the transaction and
-- applies through the Supabase CLI, which rejects CONCURRENTLY. IF NOT EXISTS makes
-- it a no-op where the index was already built concurrently by hand.
CREATE INDEX IF NOT EXISTS idx_sdm_host_device_ts
    ON public.system_device_metrics (host_name, device_id, "timestamp" DESC);
CREATE INDEX IF NOT EXISTS idx_sm_host_ts
    ON public.system_metrics (host_name, "timestamp" DESC);

-- ---------------------------------------------------------------------------
-- 1. analytics_device_status — one row per device, live
-- ---------------------------------------------------------------------------
-- The roster comes from a 24h window, not the 10-minute freshness window: a device
-- that STOPPED reporting must still appear, as 'down'. Selecting only the last
-- 10 minutes would make a dead device vanish instead, which is the exact question
-- this view exists to answer.
--
-- Written as a roster + LATERAL rather than DISTINCT ON: DISTINCT ON makes the
-- planner sort the whole window (16 479 rows -> 12, 252 ms), while the LATERAL form
-- descends idx_sdm_host_device_ts once per device (81 ms, and flat as history grows).
CREATE OR REPLACE VIEW public.analytics_device_status
WITH (security_invoker = true) AS
WITH roster AS (
    SELECT DISTINCT host_name, device_id
    FROM public.system_device_metrics
    WHERE "timestamp" > now() - interval '24 hours'
), latest AS (
    SELECT r.host_name, r.device_id, l.device_name, l.device_model, l.capture_folder,
           l.ffmpeg_status, l.monitor_status, l."timestamp"
    FROM roster r
    CROSS JOIN LATERAL (
        SELECT device_name, device_model, capture_folder,
               ffmpeg_status, monitor_status, "timestamp"
        FROM public.system_device_metrics s
        WHERE s.host_name = r.host_name AND s.device_id = r.device_id
        ORDER BY s."timestamp" DESC
        LIMIT 1
    ) l
)
SELECT
    host_name,
    device_id,
    device_name,
    device_model,
    capture_folder,
    ffmpeg_status,
    monitor_status,
    "timestamp" AS last_seen,
    CASE
        WHEN "timestamp" < now() - interval '10 minutes' THEN 'down'
        WHEN ffmpeg_status = 'active' AND monitor_status = 'active' THEN 'up'
        ELSE 'issue'
    END AS status
FROM latest;

COMMENT ON VIEW public.analytics_device_status IS
  'One row per device with a live up/issue/down verdict. Roster from the last 24h so a '
  'device that stopped reporting shows as down rather than disappearing; verdict from '
  'the last 10 minutes. ''issue'' = reporting, but ffmpeg or monitor is not active.';

-- ---------------------------------------------------------------------------
-- 2. analytics_host_status — one row per host (robot), live
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW public.analytics_host_status
WITH (security_invoker = true) AS
WITH roster AS (
    SELECT DISTINCT host_name
    FROM public.system_metrics
    WHERE "timestamp" > now() - interval '24 hours'
), latest AS (
    SELECT r.host_name, l.*
    FROM roster r
    CROSS JOIN LATERAL (
        SELECT server_name, cpu_percent, memory_percent, disk_percent,
               memory_used_gb, memory_total_gb, disk_used_gb, disk_total_gb,
               cpu_temperature_celsius, uptime_seconds, platform, "timestamp"
        FROM public.system_metrics s
        WHERE s.host_name = r.host_name
        ORDER BY s."timestamp" DESC
        LIMIT 1
    ) l
)
SELECT
    host_name,
    server_name,
    cpu_percent,
    memory_percent,
    disk_percent,
    memory_used_gb,
    memory_total_gb,
    disk_used_gb,
    disk_total_gb,
    cpu_temperature_celsius,
    uptime_seconds,
    round(uptime_seconds / 86400.0, 1) AS uptime_days,
    platform,
    "timestamp" AS last_seen,
    CASE
        WHEN "timestamp" > now() - interval '2 minutes'  THEN 'reporting'
        WHEN "timestamp" > now() - interval '10 minutes' THEN 'stale'
        ELSE 'silent'
    END AS reachability
FROM latest;

COMMENT ON VIEW public.analytics_host_status IS
  'Latest system_metrics row per host plus a reporting/stale/silent reachability verdict.';

-- ---------------------------------------------------------------------------
-- 3. analytics_incidents_daily — 90 days
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW public.analytics_incidents_daily
WITH (security_invoker = true) AS
SELECT
    date_trunc('day', detected_at)::date AS day,
    severity,
    component,
    host_name,
    device_name,
    status,
    count(*)                                        AS incidents,
    count(*) FILTER (WHERE resolved_at IS NOT NULL) AS resolved,
    avg(total_duration_minutes) FILTER (WHERE resolved_at IS NOT NULL) AS avg_duration_minutes
FROM public.system_incident
WHERE detected_at > now() - interval '90 days'
GROUP BY 1, 2, 3, 4, 5, 6;

COMMENT ON VIEW public.analytics_incidents_daily IS
  'system_incident rolled up per day x severity x component x device, last 90 days.';

-- ---------------------------------------------------------------------------
-- 4. analytics_alerts_daily — 90 days
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW public.analytics_alerts_daily
WITH (security_invoker = true) AS
SELECT
    date_trunc('day', start_time)::date AS day,
    incident_type,
    status,
    host_name,
    device_name,
    count(*)                              AS alerts,
    count(*) FILTER (WHERE checked)       AS checked,
    count(*) FILTER (WHERE discard)       AS discarded
FROM public.alerts
WHERE start_time > now() - interval '90 days'
GROUP BY 1, 2, 3, 4, 5;

COMMENT ON VIEW public.analytics_alerts_daily IS
  'alerts rolled up per day x incident_type x status x device, last 90 days.';

-- ---------------------------------------------------------------------------
-- 5. analytics_script_runs_daily — MATERIALIZED, 90 days
-- ---------------------------------------------------------------------------
-- 369 ms as a plain view. Carries team_id because script_results is the only one of
-- these tables that is tenant-scoped; callers MUST filter on it.
DROP MATERIALIZED VIEW IF EXISTS public.analytics_script_runs_daily CASCADE;
CREATE MATERIALIZED VIEW public.analytics_script_runs_daily AS
SELECT
    date_trunc('day', started_at)::date AS day,
    team_id,
    script_name,
    COALESCE(environment, 'unknown') AS environment,
    host_name,
    device_name,
    count(*)                              AS runs,
    count(*) FILTER (WHERE success)       AS passed,
    count(*) FILTER (WHERE NOT success)   AS failed,
    avg(execution_time_ms)                AS avg_duration_ms
FROM public.script_results
WHERE started_at > now() - interval '90 days'
  AND COALESCE(discard, false) = false     -- discarded runs are not results
GROUP BY 1, 2, 3, 4, 5, 6;

-- REFRESH ... CONCURRENTLY requires a unique index. These six columns are the
-- GROUP BY key, so they are unique by construction.
CREATE UNIQUE INDEX IF NOT EXISTS analytics_script_runs_daily_key
    ON public.analytics_script_runs_daily (day, team_id, script_name, environment, host_name, device_name);

COMMENT ON MATERIALIZED VIEW public.analytics_script_runs_daily IS
  'script_results rolled up per day x team x script x environment x device, last 90 days. '
  'Refreshed every 15 min by analytics_refresh_matviews(). Excludes discarded runs.';

-- ---------------------------------------------------------------------------
-- 6. analytics_device_availability_daily — MATERIALIZED, 30 days
-- ---------------------------------------------------------------------------
-- 1382 ms as a plain view: the single reason this file schedules a cron job at all.
-- One row per device per day; healthy = both capture services active that minute.
DROP MATERIALIZED VIEW IF EXISTS public.analytics_device_availability_daily CASCADE;
CREATE MATERIALIZED VIEW public.analytics_device_availability_daily AS
SELECT
    date_trunc('day', "timestamp")::date AS day,
    host_name,
    device_id,
    device_name,
    count(*) AS total_minutes,
    count(*) FILTER (
        WHERE ffmpeg_status = 'active' AND monitor_status = 'active'
    ) AS healthy_minutes,
    round(
        100.0 * count(*) FILTER (WHERE ffmpeg_status = 'active' AND monitor_status = 'active')
        / NULLIF(count(*), 0), 1
    ) AS availability_percent
FROM public.system_device_metrics
WHERE "timestamp" > now() - interval '30 days'
GROUP BY 1, 2, 3, 4;

CREATE UNIQUE INDEX IF NOT EXISTS analytics_device_availability_daily_key
    ON public.analytics_device_availability_daily (day, host_name, device_id, device_name);

COMMENT ON MATERIALIZED VIEW public.analytics_device_availability_daily IS
  'Per-device capture availability per day over the last 30 days, from system_device_metrics. '
  '1382 ms to compute, hence materialized; refreshed every 15 min.';

-- ---------------------------------------------------------------------------
-- 7. Refresh function + schedule
-- ---------------------------------------------------------------------------
-- CONCURRENTLY never blocks a reader, but it is not available everywhere: the
-- customer database is migrated through the Supabase CLI, which rejects it
-- (see docs/agent/infra). Falling back at RUNTIME rather than branching at migration
-- time keeps one function definition valid on every install. A plain refresh of a few
-- hundred rows holds its lock for milliseconds, so the fallback is not a problem.
CREATE OR REPLACE FUNCTION public.analytics_refresh_matviews()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    BEGIN
        REFRESH MATERIALIZED VIEW CONCURRENTLY public.analytics_script_runs_daily;
    EXCEPTION WHEN OTHERS THEN
        REFRESH MATERIALIZED VIEW public.analytics_script_runs_daily;
    END;

    BEGIN
        REFRESH MATERIALIZED VIEW CONCURRENTLY public.analytics_device_availability_daily;
    EXCEPTION WHEN OTHERS THEN
        REFRESH MATERIALIZED VIEW public.analytics_device_availability_daily;
    END;
END;
$$;

COMMENT ON FUNCTION public.analytics_refresh_matviews() IS
  'Refreshes the two Analytics materialized views. Falls back from CONCURRENTLY to a '
  'plain refresh where CONCURRENTLY is unavailable.';

-- ---------------------------------------------------------------------------
-- 8. Grants — service_role only on the materialized views
-- ---------------------------------------------------------------------------
-- The plain views carry security_invoker, so they inherit the base tables' RLS and
-- need no special handling. Materialized views have no RLS at all, so anon must never
-- reach them (TASK-10 service_role lockdown).
REVOKE ALL ON public.analytics_script_runs_daily         FROM PUBLIC, anon;
REVOKE ALL ON public.analytics_device_availability_daily FROM PUBLIC, anon;
GRANT SELECT ON public.analytics_script_runs_daily         TO service_role;
GRANT SELECT ON public.analytics_device_availability_daily TO service_role;

GRANT SELECT ON public.analytics_device_status    TO service_role, authenticated;
GRANT SELECT ON public.analytics_host_status      TO service_role, authenticated;
GRANT SELECT ON public.analytics_incidents_daily  TO service_role, authenticated;
GRANT SELECT ON public.analytics_alerts_daily     TO service_role, authenticated;

COMMIT;

-- ---------------------------------------------------------------------------
-- 9. pg_cron schedule (outside the transaction — cron.schedule commits its own)
-- ---------------------------------------------------------------------------
-- pg_cron is already installed and running three jobs on this database. Guarded so
-- the file still applies on an install that does not have the extension.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        PERFORM cron.unschedule('analytics_matview_refresh')
        WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'analytics_matview_refresh');

        PERFORM cron.schedule(
            'analytics_matview_refresh',
            '*/15 * * * *',
            'SELECT public.analytics_refresh_matviews();'
        );
        RAISE NOTICE 'analytics_matview_refresh scheduled every 15 minutes';
    ELSE
        RAISE WARNING 'pg_cron not installed: the Analytics materialized views will go stale. '
                      'Schedule public.analytics_refresh_matviews() by another means.';
    END IF;
END;
$$;
