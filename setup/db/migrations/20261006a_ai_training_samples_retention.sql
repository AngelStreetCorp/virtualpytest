-- 20261006a_ai_training_samples_retention.sql
-- Retention for TASK-27 training samples, wired into retention.cleanup_all().
-- Mirrors retention.cleanup_quality_metrics() in 040_quality_metrics_retention.sql.
--
-- WHY THIS EXISTS
--   ai_training_samples is the only time series on the platform with no cleanup path
--   (cleanup_all() covers system_metrics, system_device_metrics, alerts, execution_results,
--   adhoc_deployment_receipts, quality_metrics). It is also the only one whose object store
--   must never expire: TrainingStorage requires "no lifecycle (expiry) rule"
--   (cloudflare_utils.TrainingStorage). So the failure stream is uncapped in BOTH directions:
--     - failed verifications are stored with skip_cap=True (near-dup checked, cap NOT applied)
--     - alert frames are stored with skip_cap=True as well
--   A systematic failure (one bad argument replicated across a fleet -- the dns_lookuptime
--   pattern, 133 of 244 labelled rows from one hourly run) turns this from GB/year into
--   GB/quarter, with nothing ever reclaimed.
--
-- WHAT IS NEVER DELETED
--   1. eval_version IS NOT NULL  -- the frozen eval set. public.ai_training_samples_frozen_guard()
--      is a BEFORE UPDATE trigger and does NOT fire on DELETE, so this exclusion is the ONLY
--      thing standing between the scheduled cleanup and the frozen eval rows. Do not drop it.
--   2. split <> 'train'         -- 'eval' and 'holdout' rows are hand-picked, never bulk-produced.
--
-- WHAT IS DELETED
--   Unlabelled or labelled TRAIN rows older than the retention window. The default is generous
--   (180 days) because a training sample decays slowly and is expensive to re-harvest; the point
--   is to bound the runaway stream, not to keep the corpus small.
--
-- KNOWN GAP (deliberately not solved here)
--   Deleting the row does NOT delete the image: object_key points into the training bucket, and
--   that bucket must not carry a lifecycle rule. Retention here reclaims DB rows only, so images
--   whose rows were pruned become orphans in the bucket. Reconciling those is a separate job --
--   see TASK-69 step 6. With the bucket currently near-empty this is correctness for later, not
--   a live cost.
--
-- CORRECTIONS MADE BEFORE FIRST APPLICATION (2026-10-07)
--   This file was written earlier and reviewed against live production before being applied.
--   Two defects were found and fixed. Do not reintroduce them.
--
--   1. cleanup_execution_results() was listed as a member of cleanup_all(). That function was
--      DROPPED on purpose by 20260623_remove_execution_results_retention.sql: the nightly job had
--      deleted execution_results on a 7-day window and silently truncated the KPI dashboards.
--      The policy is "execution_results is NEVER deleted". Referencing the dropped function would
--      not delete anything (it is gone) -- plpgsql resolves at runtime -- it would make EVERY
--      nightly cleanup_all() raise and abort, stopping retention for all tables at once.
--
--   2. The SET search_path clause was missing. Live cleanup_all() carries
--      SET search_path TO 'retention','public','extensions'; a SECURITY DEFINER function without
--      a pinned search_path is a privilege-escalation footgun. Both functions now pin it.
--
--   The member list below is STATIC and must be kept equal to the functions that actually exist
--   in retention. 20260623 rebuilds cleanup_all() dynamically for exactly this reason. If you add
--   a cleanup_* function, add it here in the same commit or the nightly job will not call it.

BEGIN;

CREATE OR REPLACE FUNCTION retention.cleanup_training_samples()
RETURNS TABLE(
  deleted_count INTEGER,
  table_name TEXT,
  retention_days INTEGER
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'retention', 'public', 'extensions'
AS $$
DECLARE
  v_deleted_count INTEGER;
  v_days CONSTANT INTEGER := 180;
BEGIN
  DELETE FROM public.ai_training_samples
  WHERE created_at < NOW() - (v_days || ' days')::INTERVAL
    AND split = 'train'
    AND eval_version IS NULL;

  GET DIAGNOSTICS v_deleted_count = ROW_COUNT;
  RAISE NOTICE '[retention] Deleted % records from ai_training_samples (train split only, frozen rows kept, % day retention)',
    v_deleted_count, v_days;
  RETURN QUERY SELECT v_deleted_count, 'ai_training_samples'::TEXT, v_days;
END;
$$;

-- Re-create cleanup_all() to include training samples (keep existing members in sync
-- with 014_retention_schema.sql and 040_quality_metrics_retention.sql).
CREATE OR REPLACE FUNCTION retention.cleanup_all()
RETURNS TABLE(
  deleted_count INTEGER,
  table_name TEXT,
  retention_days INTEGER,
  executed_at TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'retention', 'public', 'extensions'
AS $$
BEGIN
  RAISE NOTICE '[retention] Starting scheduled cleanup at %', NOW();

  RETURN QUERY
  SELECT *, NOW() as executed_at FROM retention.cleanup_system_device_metrics()
  UNION ALL
  SELECT *, NOW() as executed_at FROM retention.cleanup_system_metrics()
  UNION ALL
  SELECT *, NOW() as executed_at FROM retention.cleanup_alerts()
  UNION ALL
  SELECT *, NOW() as executed_at FROM retention.cleanup_adhoc_deployment_receipts()
  UNION ALL
  SELECT *, NOW() as executed_at FROM retention.cleanup_quality_metrics()
  UNION ALL
  SELECT *, NOW() as executed_at FROM retention.cleanup_training_samples();

  RAISE NOTICE '[retention] Completed scheduled cleanup at %', NOW();
END;
$$;

COMMIT;