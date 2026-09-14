-- 039_quality_metrics.sql
-- Audio/Video Quality (AVQ) per-minute metrics.
-- One row per device per minute, written by backend_host/scripts/avq_monitor.py.
-- Mirrors the cadence/shape of system_device_metrics (1 row/device/minute).
-- See docs/agent/AVQ_IMPLEMENTATION.md.

CREATE TABLE IF NOT EXISTS quality_metrics (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    host_name       text NOT NULL,
    device_id       text NOT NULL,
    device_name     text NOT NULL,
    capture_folder  text NOT NULL,
    timestamp       timestamptz NOT NULL DEFAULT now(),   -- minute bucket
    window_seconds  numeric NOT NULL DEFAULT 60,

    -- video (spatial quality from full-res JPEG captures)
    blurriness_score    numeric,   -- ffmpeg blurdetect "blur mean" (higher = blurrier)
    blockiness_score    numeric,   -- ffmpeg blockdetect "block mean"
    jerkiness_score     numeric,   -- temporal info proxy (0..1), approximate
    clean_video_seconds numeric,   -- seconds with no active video incident
    video_availability  numeric,   -- 0..1
    video_mos           numeric,   -- 1..5, APPROXIMATE

    -- audio (from 10-min MP3 chunks)
    loudness_lkfs       numeric,   -- ebur128 Integrated loudness (LUFS = LKFS)
    loudness_range      numeric,   -- ebur128 LRA (LU)
    true_peak_dbtp      numeric,   -- ebur128 true peak (dBTP)
    saturation_score    numeric,   -- clipping proxy (0..1)
    silence_seconds     numeric,   -- total silence in the window
    audio_availability  numeric,   -- 0..1
    audio_mos           numeric,   -- 1..5, APPROXIMATE

    events  jsonb,   -- run-length incidents {freeze:{count,totalMs,avgMs,longestMs}, ...}
    positions jsonb, -- RLE'd Localize screen position [{s,e,node,kind,conf}, ...] (epoch ms)
    created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quality_metrics_ts        ON quality_metrics(timestamp);
CREATE INDEX IF NOT EXISTS idx_quality_metrics_device_ts ON quality_metrics(device_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_quality_metrics_host      ON quality_metrics(host_name);

COMMENT ON TABLE quality_metrics IS
  'Per-minute audio/video quality KPIs per device (AVQ). Written by avq_monitor.py. MOS columns are approximate.';

-- Row Level Security: platform default (RLS on, open policy; authz lives in the server layer)
ALTER TABLE quality_metrics ENABLE ROW LEVEL SECURITY;
CREATE POLICY "quality_metrics_access_policy" ON quality_metrics
FOR ALL TO public USING (true);
