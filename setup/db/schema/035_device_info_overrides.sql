-- 035 — Device info value correction (manual overrides + read-time corrected views).
--
-- device_get_info / get_info extract device info via OCR into
-- script_results.metadata->'info' (free-form JSONB; keys vary per UI/panel).
-- OCR errors can be systematic (wrong on every scan), so historical consensus
-- alone can't fix them. This adds a non-destructive, read-time correction
-- layer keyed on the literal info key (no fixed field schema):
--   * device_info_overrides  — per-device, per-key human-entered correct value
--   * device_info_corrected  — latest scan per device, overrides overlaid (Grafana)
--   * device_info_key_status — per-key detail for the editor UI
-- Raw OCR in script_results is never mutated. See docs/agent/.

-- info_source ('device' | 'gateway') lets the SAME override table/routes/editor
-- serve both device info (OCR, metadata->'info') and gateway info (gw_info, flat
-- metadata). It is part of the unique key because device and gateway info share
-- keys (e.g. both have serial_number) for the same (device, host) — without the
-- discriminator one override would wrongly apply to both. Gateway views live in
-- 036_gateway_info.sql.
CREATE TABLE IF NOT EXISTS public.device_info_overrides (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id            uuid NOT NULL,
    device_name        text NOT NULL,
    host_name          text NOT NULL,
    userinterface_name text NOT NULL DEFAULT '',
    info_source        text NOT NULL DEFAULT 'device',
    info_key           text NOT NULL,
    corrected_value    text NOT NULL,
    raw_value_at_edit  text,
    note               text,
    updated_by         text,
    created_at         timestamptz NOT NULL DEFAULT NOW(),
    updated_at         timestamptz NOT NULL DEFAULT NOW(),
    CONSTRAINT device_info_overrides_unique
        UNIQUE (team_id, device_name, host_name, userinterface_name, info_source, info_key)
);

CREATE INDEX IF NOT EXISTS idx_device_info_overrides_lookup
    ON public.device_info_overrides (team_id, device_name, host_name, userinterface_name, info_source);

ALTER TABLE public.device_info_overrides ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "device_info_overrides_access_policy" ON public.device_info_overrides;
CREATE POLICY "device_info_overrides_access_policy" ON public.device_info_overrides
FOR ALL
TO public
USING (true)
WITH CHECK (true);

-- DROP + CREATE (not CREATE OR REPLACE): CREATE OR REPLACE can only append
-- columns at the end, so it errors when re-applied over a view with a different
-- column set/order. DROP first keeps this re-runnable in any order.
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

CREATE OR REPLACE VIEW public.device_info_key_status AS
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

-- Views run with the caller's privileges (not the owner's): RLS of the
-- underlying tables applies to whoever reads the view (Studio lint
-- security_definer_view).
ALTER VIEW public.device_info_corrected SET (security_invoker = on);
ALTER VIEW public.device_info_key_status SET (security_invoker = on);
