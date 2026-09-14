-- 20260620_quality_metrics_positions.sql
-- AVQ: add RLE'd Localize screen-position spans to the per-minute quality_metrics row.
-- positions = [{s,e,node,kind,conf}, ...] where s/e are epoch ms, kind ∈
-- {confident, ambiguous, no_signal, blackscreen, unknown}. Written by
-- avq_analyze.analyze_positions() from the per-frame `localize` field. NULL when
-- Localize is disabled for the device (no DEVICE{N}_USERINTERFACE).

ALTER TABLE quality_metrics ADD COLUMN IF NOT EXISTS positions jsonb;
