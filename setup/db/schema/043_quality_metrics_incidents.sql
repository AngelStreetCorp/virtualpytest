-- 043_quality_metrics_incidents.sql
-- Blackscreen / freeze / macroblocks coverage per minute, aggregated from the
-- realtime detector's per-frame metadata. Blackscreen+freeze also drive
-- video_availability down (so video_mos→0 on a black/frozen channel).

ALTER TABLE quality_metrics
  ADD COLUMN IF NOT EXISTS blackscreen_seconds  numeric,
  ADD COLUMN IF NOT EXISTS freeze_seconds       numeric,
  ADD COLUMN IF NOT EXISTS macroblocks_seconds  numeric;
