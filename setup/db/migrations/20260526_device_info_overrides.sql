-- 20260526 — Manual value correction for device get_info metadata.
--
-- The `device_get_info` / `get_info` script extracts device info via OCR into
-- script_results.metadata->'info' (a free-form JSONB object). OCR sometimes
-- misreads values (e.g. build_version "5.27" read as "B27"), and these errors
-- can be *systematic* (wrong on every scan), so historical consensus cannot
-- fix them on its own. Field names are NOT fixed — they vary per UI/panel
-- (a gateway has no software_version; an STB does) — so correction must be
-- generic over arbitrary keys.
--
-- This migration adds a non-destructive, read-time correction layer:
--   * device_info_overrides  — per-device, per-key human-entered correct value
--   * device_info_corrected  — latest scan per device with overrides overlaid
--                              onto the raw info JSONB (used by Grafana)
--   * device_info_key_status — per-key detail for the editor UI: raw value,
--                              override, effective value, stale flag (raw
--                              changed since the override was set)
--
-- Note: no history/consensus suggestion. Frequency cannot distinguish an OCR
-- slip from a real version bump (e.g. AH-1 -> AH-2), so the only correction is
-- the manual override; the views just overlay it.
--
-- Raw OCR in script_results is left untouched (it is also the OCR-quality
-- audit trail). See docs/agent/ (DEVICE_INFO_CORRECTION.md).

BEGIN;

-- ---------------------------------------------------------------------------
-- Override table: one row per (device, host, ui, info_key).
-- Identity is device_name + host_name (platform-assigned, NOT OCR'd) — never
-- the OCR'd serial. userinterface_name is part of the key (a device could in
-- principle be scanned under different UIs) and is NOT NULL so the UNIQUE
-- constraint is reliable.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.device_info_overrides (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id            uuid NOT NULL,
    device_name        text NOT NULL,
    host_name          text NOT NULL,
    userinterface_name text NOT NULL DEFAULT '',
    info_key           text NOT NULL,
    corrected_value    text NOT NULL,
    raw_value_at_edit  text,            -- raw OCR value when the human corrected it
    note               text,
    updated_by         text,            -- editor email
    created_at         timestamptz NOT NULL DEFAULT NOW(),
    updated_at         timestamptz NOT NULL DEFAULT NOW(),
    CONSTRAINT device_info_overrides_unique
        UNIQUE (team_id, device_name, host_name, userinterface_name, info_key)
);

CREATE INDEX IF NOT EXISTS idx_device_info_overrides_lookup
    ON public.device_info_overrides (team_id, device_name, host_name, userinterface_name);

COMMENT ON TABLE public.device_info_overrides IS
'Per-device, per-key manual corrections for OCR-extracted device info '
'(script_results.metadata->''info''). Applied at read time by device_info_corrected; '
'raw data in script_results is never mutated.';
COMMENT ON COLUMN public.device_info_overrides.info_key IS
'The literal JSONB key inside metadata->''info'' to correct (e.g. "build_version", '
'"OV_Power_Status"). Field set is dynamic per UI — no fixed schema.';
COMMENT ON COLUMN public.device_info_overrides.raw_value_at_edit IS
'Raw OCR value at the moment of correction. If a later scan''s raw value differs, '
'the underlying value actually changed (e.g. firmware update) and the override is '
'flagged stale for review rather than silently applied.';

ALTER TABLE public.device_info_overrides ENABLE ROW LEVEL SECURITY;
-- Idempotent: re-running the migration on a DB that already has the policy
-- must not fail (CREATE POLICY has no IF NOT EXISTS).
DROP POLICY IF EXISTS "device_info_overrides_access_policy" ON public.device_info_overrides;
CREATE POLICY "device_info_overrides_access_policy" ON public.device_info_overrides
FOR ALL
TO public
USING ((auth.uid() IS NULL) OR (auth.role() = 'service_role'::text) OR true)
WITH CHECK ((auth.uid() IS NULL) OR (auth.role() = 'service_role'::text) OR true);

-- ---------------------------------------------------------------------------
-- device_info_corrected — latest get_info scan per device, with overrides
-- overlaid onto the raw info JSONB by key (generic; no key assumptions).
-- Grafana reads info_corrected->>'<key>'.
-- ---------------------------------------------------------------------------
-- DROP + CREATE (not CREATE OR REPLACE): the column set has grown over time
-- (report-artifact columns were added later — see 20260526_d). CREATE OR REPLACE
-- can only append columns at the end, so re-running an older definition over a
-- newer view fails with "cannot drop columns from view". DROP first makes every
-- version of this file safe to (re-)apply in any order. No DB object depends on
-- this view (Grafana reads it externally), so no CASCADE is needed.
DROP VIEW IF EXISTS public.device_info_corrected;
CREATE VIEW public.device_info_corrected AS
WITH latest AS (
    SELECT DISTINCT ON (sr.team_id, sr.device_name, sr.host_name)
        sr.team_id,
        sr.device_name,
        sr.host_name,
        sr.userinterface_name,
        sr.started_at,
        sr.html_report_r2_url,
        sr.metadata->'info' AS info_raw,
        -- Report artifacts (presigned R2 URLs) stamped on every script run by
        -- ScriptExecutor; surfaced here for the latest get_info scan.
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
    GROUP BY team_id, device_name, host_name, userinterface_name
)
SELECT
    l.team_id,
    l.device_name,
    l.host_name,
    l.userinterface_name,
    l.started_at,
    l.html_report_r2_url,
    l.info_raw,
    -- right side of || wins; keys not overridden are preserved. NULL overrides
    -- (no rows) → || NULL → NULL, so COALESCE falls back to the raw object.
    COALESCE(l.info_raw || ov.overrides, l.info_raw) AS info_corrected,
    (ov.overrides IS NOT NULL) AS has_override,
    l.initial_screenshot_url,
    l.final_screenshot_url,
    l.video_url
FROM latest l
LEFT JOIN ov
    ON  ov.team_id            = l.team_id
    AND ov.device_name        = l.device_name
    AND ov.host_name          = l.host_name
    AND ov.userinterface_name IS NOT DISTINCT FROM COALESCE(l.userinterface_name, '');

COMMENT ON VIEW public.device_info_corrected IS
'Latest get_info scan per (team, device, host) with device_info_overrides '
'overlaid onto metadata->''info'' by key. Non-destructive. info_corrected is the '
'value to display; info_raw is the original OCR. *_screenshot_url / video_url are '
'the scan report''s presigned R2 artifacts (latest scan only).';

-- ---------------------------------------------------------------------------
-- device_info_key_status — per-key detail for the editor UI.
-- For each key in the latest scan: raw value, override (if any), effective
-- value, and override_stale (raw changed since the override was set).
-- ---------------------------------------------------------------------------
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
    lk.info_key,
    lk.raw_value,
    o.corrected_value                          AS override_value,
    (o.id IS NOT NULL)                         AS is_overridden,
    COALESCE(o.corrected_value, lk.raw_value)  AS effective_value,
    (o.id IS NOT NULL AND o.raw_value_at_edit IS DISTINCT FROM lk.raw_value) AS override_stale
FROM latest_kv lk
LEFT JOIN public.device_info_overrides o
    ON  o.team_id            = lk.team_id
    AND o.device_name        = lk.device_name
    AND o.host_name          = lk.host_name
    AND o.userinterface_name IS NOT DISTINCT FROM COALESCE(lk.userinterface_name, '')
    AND o.info_key           = lk.info_key;

COMMENT ON VIEW public.device_info_key_status IS
'Per-key correction status for the latest get_info scan per device: raw value, '
'override, effective value, and override_stale (raw changed since the override '
'was set). No history/suggestion. Drives the Device Info editor.';

COMMIT;
