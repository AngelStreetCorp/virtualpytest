-- 20261014c_monitor_status_off_rollback.sql — TASK-95: a device on the tv_lite monitor profile reports monitor_status = 'off' (no monitor runs for it on purpose).
-- The device status view, the availability summary and the daily availability matview counted only 'active' as healthy, so every tv_lite device
-- would read 'issue' and 0 % available. Puts the three definitions back as they were: only 'active' counts as healthy.
-- The matview is dropped WITHOUT CASCADE (the schema file uses CASCADE): if something depends on it this fails and changes nothing.
-- Re-run safe. Inverse of 20261014c_monitor_status_off.sql. Not applied anywhere yet (owner decision); apply BEFORE the first tv_lite device.

BEGIN;

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

CREATE OR REPLACE VIEW device_availability_summary
WITH (security_invoker = true)
AS
WITH device_availability AS (
    SELECT 
        system_device_metrics.device_name,
        system_device_metrics.capture_folder,
        count(*) AS total_minutes,
        count(
            CASE
                WHEN ((system_device_metrics.ffmpeg_status = 'active'::text) AND (system_device_metrics.monitor_status = 'active'::text)) THEN 1
                ELSE NULL::integer
            END) AS healthy_minutes
    FROM system_device_metrics
    WHERE (system_device_metrics."timestamp" >= (now() - '01:00:00'::interval))
    GROUP BY system_device_metrics.device_name, system_device_metrics.capture_folder
)
SELECT 
    device_name,
    capture_folder,
    round((((healthy_minutes)::numeric * 100.0) / (total_minutes)::numeric), 2) AS availability_percent,
    CASE
        WHEN ((((healthy_minutes)::numeric * 100.0) / (total_minutes)::numeric) < (90)::numeric) THEN 1
        ELSE 0
    END AS is_low_availability
FROM device_availability
WHERE (total_minutes > 10);

DROP MATERIALIZED VIEW IF EXISTS public.analytics_device_availability_daily;
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

REFRESH MATERIALIZED VIEW public.analytics_device_availability_daily;

-- A recreated materialized view gets default privileges, and matviews have no RLS: restate what 048_analytics_views.sql section 8 grants (TASK-10 lockdown).
REVOKE ALL ON public.analytics_device_availability_daily FROM PUBLIC, anon;
GRANT SELECT ON public.analytics_device_availability_daily TO service_role;

COMMIT;
