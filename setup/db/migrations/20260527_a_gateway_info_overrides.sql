-- 20260527_a — Per-device GATEWAY info, parallel to device info.
--
-- A gateway is an *environment* parameter of a device (the LAN a device sits
-- behind), and different declared devices on the same host can be behind
-- different gateways — so gateway info is keyed per (team, device, host), exactly
-- like device info. gw_info now runs device-targeted (records the run target's
-- device_name); the host machine running the devices is never itself an entity.
--
-- gw_info stores its router fields FLAT at the top level of script_results.metadata
-- (NOT nested under 'info'), and the gateway-info Grafana dashboard reads that flat
-- shape. We DO NOT reshape stored metadata — the gateway_info_* views curate the
-- flat metadata into an `info` object at read time, so Grafana is untouched.
--
-- The override layer is generalised, not duplicated: device_info_overrides gains an
-- `info_source` column ('device' | 'gateway') so the same table/routes/editor serve
-- both. A discriminator is REQUIRED because device and gateway info share keys
-- (e.g. both have `serial_number`) for the same (device, host) — without it a single
-- override would wrongly apply to both. See docs/agent/devices/DEVICE_INFO_CORRECTION.md.

BEGIN;

-- ── 1. Generalise the override table with a source discriminator ──────────────
ALTER TABLE public.device_info_overrides
    ADD COLUMN IF NOT EXISTS info_source text NOT NULL DEFAULT 'device';

-- Re-key uniqueness/index on (… , info_source, info_key): the same key can now be
-- overridden independently per source for the same device.
ALTER TABLE public.device_info_overrides
    DROP CONSTRAINT IF EXISTS device_info_overrides_unique;
ALTER TABLE public.device_info_overrides
    ADD CONSTRAINT device_info_overrides_unique
        UNIQUE (team_id, device_name, host_name, userinterface_name, info_source, info_key);

DROP INDEX IF EXISTS idx_device_info_overrides_lookup;
CREATE INDEX IF NOT EXISTS idx_device_info_overrides_lookup
    ON public.device_info_overrides (team_id, device_name, host_name, userinterface_name, info_source);

-- ── 2. Device views: restrict the override overlay to source='device' ─────────
-- (Otherwise a gateway override on a shared key would bleed into the device view.)
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

DROP VIEW IF EXISTS public.device_info_key_status;
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

-- ── 3. Gateway views (curate flat gw_info metadata → `info` object) ───────────
-- gw_info stores router fields flat at the top of metadata. We strip the
-- operational/debug keys (blacklist) so only environment fields remain; this is
-- the gateway equivalent of metadata->'info'. Only successful, device-attributed
-- scans are surfaced (auth_success=true and a real device target, never 'host').
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

COMMENT ON VIEW public.gateway_info_corrected IS
'Latest gw_info scan per (team, device, host) with gateway overrides '
'(device_info_overrides where info_source=''gateway'') overlaid. info_raw is the '
'flat gw_info metadata minus operational keys; storage is never reshaped (Grafana '
'reads the flat metadata directly).';

COMMIT;
