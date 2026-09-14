-- 036 — Per-device GATEWAY info views (read-time curation + correction overlay).
--
-- A gateway is an ENVIRONMENT parameter of a device (the LAN a device sits behind);
-- different declared devices on the same host can be behind different gateways, so
-- gateway info is keyed per (team, device, host) — exactly like device info. The
-- run target supplies the device identity: gw_info runs device-targeted and its
-- script_results row carries the real device_name (never the host machine).
--
-- gw_info stores its router fields FLAT at the top level of script_results.metadata
-- (not nested under 'info'); the gateway-info Grafana dashboard reads that flat
-- shape. These views DO NOT reshape storage — they curate the flat metadata into an
-- `info` object at read time by stripping operational/debug keys (blacklist), which
-- is the gateway equivalent of metadata->'info'.
--
-- Corrections reuse public.device_info_overrides with info_source='gateway' (see
-- 035_device_info_overrides.sql). Only successful, device-attributed scans surface.
-- See docs/agent/devices/DEVICE_INFO_CORRECTION.md.
--
-- SUPERSEDED by 046_gw_info_latest.sql (TASK-16): the `latest` CTE below scanned
-- every gw_info row per read; 046 keeps the same views over the trigger-maintained
-- gw_info_latest table. The definitions are left here as the reference for the
-- view contract; 046 drops and recreates both views.

DROP VIEW IF EXISTS public.gateway_info_corrected;
CREATE VIEW public.gateway_info_corrected AS
WITH latest AS (
    SELECT DISTINCT ON (sr.team_id, sr.device_name, sr.host_name)
        sr.team_id, sr.device_name, sr.host_name, sr.userinterface_name,
        sr.started_at, sr.html_report_r2_url,
        (sr.metadata
            - 'gateway_url' - 'gateway_profile' - 'selected_profile' - 'protocol'
            - 'requested_protocol' - 'auth_success' - 'profile_attempts'
            - 'config_path' - 'timestamp' - 'host_name' - 'report_artifacts'
            - 'profile_name' - 'device_name' - 'device_model' - 'device_id'
        ) AS info_raw,
        sr.metadata->'report_artifacts'->>'initial_screenshot_url' AS initial_screenshot_url,
        sr.metadata->'report_artifacts'->>'final_screenshot_url'   AS final_screenshot_url,
        sr.metadata->'report_artifacts'->>'video_url'              AS video_url
    FROM public.script_results sr
    WHERE sr.script_name = 'gw_info'
      AND sr.metadata->>'auth_success' = 'true'
      AND sr.device_name IS NOT NULL
      AND sr.device_name <> 'host'
    ORDER BY sr.team_id, sr.device_name, sr.host_name, sr.started_at DESC
),
ov AS (
    SELECT team_id, device_name, host_name, userinterface_name,
           jsonb_object_agg(info_key, to_jsonb(corrected_value)) AS overrides
    FROM public.device_info_overrides
    WHERE info_source = 'gateway'
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

DROP VIEW IF EXISTS public.gateway_info_key_status;
CREATE VIEW public.gateway_info_key_status AS
WITH latest AS (
    SELECT DISTINCT ON (sr.team_id, sr.device_name, sr.host_name)
        sr.team_id, sr.device_name, sr.host_name, sr.userinterface_name,
        (sr.metadata
            - 'gateway_url' - 'gateway_profile' - 'selected_profile' - 'protocol'
            - 'requested_protocol' - 'auth_success' - 'profile_attempts'
            - 'config_path' - 'timestamp' - 'host_name' - 'report_artifacts'
            - 'profile_name' - 'device_name' - 'device_model' - 'device_id'
        ) AS info
    FROM public.script_results sr
    WHERE sr.script_name = 'gw_info'
      AND sr.metadata->>'auth_success' = 'true'
      AND sr.device_name IS NOT NULL
      AND sr.device_name <> 'host'
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
    AND o.info_source = 'gateway'
    AND o.info_key = lk.info_key;

-- Views run with the caller's privileges (not the owner's): RLS of the
-- underlying tables applies to whoever reads the view (Studio lint
-- security_definer_view).
ALTER VIEW public.gateway_info_corrected SET (security_invoker = on);
ALTER VIEW public.gateway_info_key_status SET (security_invoker = on);
