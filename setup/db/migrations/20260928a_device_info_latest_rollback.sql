-- 20260928a_device_info_latest_rollback.sql
--
-- Reverts 20260928a_device_info_latest.sql: drops the trigger and the
-- device_info_latest table, and restores device_info_corrected /
-- device_info_key_status to the read-time DISTINCT ON definitions of
-- setup/db/schema/035_device_info_overrides.sql (same columns either way, so
-- nothing downstream changes).
--
-- Loses nothing: device_info_latest is derived entirely from script_results,
-- which this never touches. device_info_overrides is untouched too.

-- 1) Views back to the 035 read-time definitions -----------------------------
DROP VIEW IF EXISTS public.device_info_key_status;
DROP VIEW IF EXISTS public.device_info_corrected;

CREATE VIEW public.device_info_corrected AS
WITH latest AS (
    SELECT DISTINCT ON (sr.team_id, sr.device_name, sr.host_name)
        sr.team_id, sr.device_name, sr.host_name, sr.userinterface_name,
        sr.started_at, sr.html_report_r2_url,
        sr.metadata->'info' AS info_raw,
        sr.metadata->'report_artifacts'->>'initial_screenshot_url' AS initial_screenshot_url,
        sr.metadata->'report_artifacts'->>'final_screenshot_url'   AS final_screenshot_url,
        sr.metadata->'report_artifacts'->>'video_url'              AS video_url
    FROM public.script_results sr
    WHERE sr.script_name IN ('get_info', 'device_get_info')
      AND jsonb_typeof(sr.metadata->'info') = 'object'
    ORDER BY sr.team_id, sr.device_name, sr.host_name, sr.started_at DESC
),
ov AS (
    SELECT team_id, device_name, host_name, userinterface_name,
           jsonb_object_agg(info_key, to_jsonb(corrected_value)) AS overrides
    FROM public.device_info_overrides
    WHERE info_source = 'device'
    GROUP BY team_id, device_name, host_name, userinterface_name
)
SELECT
    l.team_id, l.device_name, l.host_name, l.userinterface_name,
    l.started_at, l.html_report_r2_url,
    l.info_raw,
    COALESCE(l.info_raw || ov.overrides, l.info_raw) AS info_corrected,
    (ov.overrides IS NOT NULL) AS has_override,
    l.initial_screenshot_url, l.final_screenshot_url, l.video_url
FROM latest l
LEFT JOIN ov
    ON  ov.team_id            = l.team_id
    AND ov.device_name        = l.device_name
    AND ov.host_name          = l.host_name
    AND ov.userinterface_name IS NOT DISTINCT FROM COALESCE(l.userinterface_name, '');

CREATE VIEW public.device_info_key_status AS
WITH latest AS (
    SELECT DISTINCT ON (sr.team_id, sr.device_name, sr.host_name)
        sr.team_id, sr.device_name, sr.host_name, sr.userinterface_name,
        sr.metadata->'info' AS info
    FROM public.script_results sr
    WHERE sr.script_name IN ('get_info', 'device_get_info')
      AND jsonb_typeof(sr.metadata->'info') = 'object'
    ORDER BY sr.team_id, sr.device_name, sr.host_name, sr.started_at DESC
),
latest_kv AS (
    SELECT l.team_id, l.device_name, l.host_name, l.userinterface_name,
           kv.key AS info_key, kv.value AS raw_value
    FROM latest l
    CROSS JOIN LATERAL jsonb_each_text(l.info) AS kv(key, value)
)
SELECT
    lk.team_id, lk.device_name, lk.host_name, lk.userinterface_name,
    lk.info_key, lk.raw_value,
    o.corrected_value                              AS override_value,
    (o.id IS NOT NULL)                             AS is_overridden,
    COALESCE(o.corrected_value, lk.raw_value)      AS effective_value,
    (o.id IS NOT NULL AND o.raw_value_at_edit IS DISTINCT FROM lk.raw_value) AS override_stale
FROM latest_kv lk
LEFT JOIN public.device_info_overrides o
    ON  o.team_id = lk.team_id AND o.device_name = lk.device_name
    AND o.host_name = lk.host_name
    AND o.userinterface_name IS NOT DISTINCT FROM COALESCE(lk.userinterface_name, '')
    AND o.info_source = 'device'
    AND o.info_key = lk.info_key;

ALTER VIEW public.device_info_corrected  SET (security_invoker = on);
ALTER VIEW public.device_info_key_status SET (security_invoker = on);

-- 2) Trigger, function and table --------------------------------------------
DROP TRIGGER IF EXISTS trg_device_info_track ON public.script_results;
DROP FUNCTION IF EXISTS public.device_info_track();
DROP TABLE IF EXISTS public.device_info_latest;
