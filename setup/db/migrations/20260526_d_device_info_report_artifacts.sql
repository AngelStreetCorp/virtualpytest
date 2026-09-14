-- 20260526_d — Surface the get_info scan's report artifacts (signed R2 URLs) on
-- device_info_corrected so the Device Info page can show the "Final State"
-- screenshot (and link the initial screenshot / test video) without re-deriving
-- R2 object paths.
--
-- The script executor now stamps script_results.metadata->'report_artifacts'
-- with the presigned URLs it already minted for the report:
--   { initial_screenshot_url, final_screenshot_url, video_url }
-- These are presigned (~7-day expiry); the Device Info page only ever shows the
-- LATEST scan, which is normally well within that window. No re-signing here —
-- the stored URL is passed straight through.
--
-- Only the device_info_corrected view changes (adds three columns); the
-- override table and device_info_key_status are untouched. See
-- docs/agent/devices/DEVICE_INFO_CORRECTION.md.

BEGIN;

-- DROP + CREATE rather than CREATE OR REPLACE: the latter can only append
-- columns at the end and errors ("cannot drop columns from view" / "cannot
-- change name of view column") whenever the existing view's column set differs
-- in count or order. DROP first makes this safe to (re-)apply over ANY prior
-- definition. No DB object depends on the view (Grafana reads it externally).
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
    -- New columns MUST be appended at the end: CREATE OR REPLACE VIEW cannot
    -- reorder/insert columns ahead of the existing ones.
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

COMMIT;
