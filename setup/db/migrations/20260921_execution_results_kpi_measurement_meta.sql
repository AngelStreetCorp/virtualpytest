-- KPI measurement confidence
--
-- A KPI is `matched frame mtime - action timestamp`, with no interpolation, so the
-- value is quantised to the gap between the two frames around the transition. That
-- gap is 200 ms when the frames come from hot storage (5 fps) and up to 1 s when the
-- window is old enough to be served from the cold archive — and nothing recorded which
-- of the two produced a given number. 1227 ms could mean +/-200 ms or +/-1000 ms and
-- the report showed both identically, which is what made the measurements arguable.
--
-- This column stores the evidence alongside the value: effective fps over the
-- action->match window, how many frames went missing, which storage served them, and
-- the interval the change is provably inside. It has to be stored rather than
-- recomputed, because the frames are deleted from the capture buffer within minutes.
--
-- Written by shared/src/lib/database/execution_results_db.update_execution_result_with_kpi,
-- built by shared/src/lib/utils/kpi_confidence.measurement_confidence.

ALTER TABLE execution_results
  ADD COLUMN IF NOT EXISTS kpi_measurement_meta jsonb;

COMMENT ON COLUMN execution_results.kpi_measurement_meta IS
  'KPI measurement confidence: fps_effective, interval_ms_median/p95/max, frames_missed, gaps, precision_ms, source (hot/cold/mixed/none), verified_bracket_ms, algorithm, captures_scanned, has_frame_evidence.';

-- Dashboards filter on the weak ones (archive-sourced, or no frame evidence at all),
-- which is a small slice of the table, so a partial index is enough.
CREATE INDEX IF NOT EXISTS idx_execution_results_kpi_meta_source
  ON execution_results ((kpi_measurement_meta->>'source'))
  WHERE kpi_measurement_meta IS NOT NULL;
