-- 042_quality_metrics_audio_level.sql
-- Raw audio level (ffmpeg volumedetect mean_volume, dB) — distinct from the
-- K-weighted/gated loudness_lkfs (ebur128). Same metric shown on the live overlay.

ALTER TABLE quality_metrics
  ADD COLUMN IF NOT EXISTS audio_level_db numeric;
