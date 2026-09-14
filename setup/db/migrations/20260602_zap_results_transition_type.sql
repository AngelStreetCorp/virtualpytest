-- Persist the blackscreen/freeze transition type on each zap event.
-- The detector already computes transition_type ('freeze' | 'blackscreen') — it drives the
-- per-event report label — but it was never stored, so blackscreen and freeze durations were
-- indistinguishable in zap_results (both land in blackscreen_freeze_duration_seconds).
-- Storing it lets the "All Zapping Events" Grafana dashboard split mean duration into separate
-- blackscreen vs freeze panels. Written via the same two funnels that set the duration:
-- zapping_detector_utils._store_zapping_event (automatic monitoring) and
-- zap_statistics.record_iteration_to_db (script zap). Existing rows stay NULL.

ALTER TABLE zap_results ADD COLUMN IF NOT EXISTS transition_type text;

COMMENT ON COLUMN zap_results.transition_type IS 'Transition type of the zap event: ''freeze'' or ''blackscreen''. NULL for rows recorded before this column existed.';
